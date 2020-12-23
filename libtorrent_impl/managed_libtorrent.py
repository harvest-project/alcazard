import asyncio
import logging
import os
import time
import traceback
from asyncio import CancelledError
from concurrent.futures.thread import ThreadPoolExecutor

import peewee

import migrations
import models
from alcazar_logging import BraceAdapter
from clients import Manager, PeriodicTaskInfo, TorrentBatchUpdate, TorrentAlreadyAddedException
from error_manager import Severity
from libtorrent_impl import params, lt_models
from libtorrent_impl.speedups import session
from libtorrent_impl.utils import LibtorrentClientException

logger = BraceAdapter(logging.getLogger(__name__))


class ManagedLibtorrent(Manager):
    key = 'managed_libtorrent'
    config_model = models.ManagedLibtorrentConfig

    def __init__(self, orchestrator, instance_config):
        super().__init__(orchestrator, instance_config)

        self._state_path = os.path.join(self.config.state_path, self._name, 'db.sqlite3')
        self._peer_port = None
        self._session = None
        # Timestamp (float) of when the last torrent updates request was posted.
        self._last_post_updates_request = None
        # Timestamp (float) of when the last resume data save was triggered
        self._last_save_resume_data_request = None
        # Used to cache Torrent model instances that we add during startup to avoid issuing N selects
        self._libtorrent_torrent_by_info_hash = {}
        # Number of torrents waiting for resume data. Used during shutdown.
        self._num_waiting_for_resume_data = 0
        # Metrics refreshed together with session stats
        self._metrics = None
        # Timer stats from the C++ session manager
        self._timer_stats = None

        self._periodic_tasks.append(PeriodicTaskInfo(self._post_torrent_updates, params.POST_UPDATES_INTERVAL))
        self._save_resume_data_task = PeriodicTaskInfo(self._periodic_resume_save, params.SAVE_RESUME_DATA_INTERVAL)
        self._periodic_tasks.append(self._save_resume_data_task)
        self._periodic_tasks.append(
            PeriodicTaskInfo(self._update_session_stats, params.UPDATE_SESSION_STATS_INTERVAL))

        self._executor = ThreadPoolExecutor(1, self._name)
        self._event_loop = asyncio.get_event_loop()

    async def _exec(self, fn, *args):
        try:
            future = self._event_loop.run_in_executor(self._executor, fn, *args)
        except RuntimeError as exc:
            logger.debug('Got RuntimeError in _exec, refreshing _event_loop.')
            # Event loop might be closed
            self._event_loop = asyncio.get_event_loop()
            future = self._event_loop.run_in_executor(self._executor, fn, *args)
        return await future

    @property
    def peer_port(self):
        return self._peer_port

    def launch(self):
        super().launch()

        logger.debug('Initializing DB for libtorrent at {}.'.format(self._state_path))
        os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
        db = peewee.SqliteDatabase(self._state_path)
        lt_models.LT_DB.initialize(db)
        with db:
            migrations.apply_migrations(lt_models.LT_DB, lt_models.LT_MODELS, lt_models.LT_MIGRATIONS)
            try:
                lt_models.SessionStats.select().get()
            except peewee.DoesNotExist:
                lt_models.SessionStats(
                    total_downloaded=0,
                    total_uploaded=0,
                ).save()

        self._peer_port = self._orchestrator.grab_peer_port()
        logger.debug('Received peer_port={} for {}', self._peer_port, self._name)

        # Reset the timer for saving fast resume data when launched, no need to do it immediately.
        self._save_resume_data_task.last_run_at = time.time()

        self._session = session.LibtorrentSession(
            manager=self,
            db_path=self._state_path,
            listen_interfaces='0.0.0.0:{0},[::]:{0}'.format(self._peer_port),
        )

        asyncio.ensure_future(self._loop())
        asyncio.ensure_future(self._load_initial_torrents())

    async def _load_initial_torrents(self):
        logger.info('Starting initial torrent load.')
        start = time.time()
        num_loaded = await self._exec(self._session.load_initial_torrents)
        while True:
            if not self._metrics or num_loaded > self._metrics.get('alcazar.torrents.count[gauge]'):
                logger.debug('Still waiting for batch to load.')
                await asyncio.sleep(2)
                continue

            logger.info('Loading initial torrent batch...')
            new_num_loaded = await self._exec(self._session.load_initial_torrents)
            if new_num_loaded == num_loaded:
                break
            num_loaded = new_num_loaded
            await asyncio.sleep(2)
        logger.info('Completed initial torrent load in {}.', time.time() - start)

    async def _loop(self):
        while True:
            start = time.time()

            try:
                await self._run_periodic_tasks()
                await self._process_alerts(shutting_down=False)
            except CancelledError:
                break
            except Exception:
                self._error_manager.add_error(
                    severity=Severity.ERROR,
                    key=params.ERROR_KEY_LOOP,
                    message='Loop crashed',
                    traceback=traceback.format_exc(),
                )
                logger.exception('Loop crashed')

            time_taken = time.time() - start
            if time_taken > params.SLOW_LOOP_THRESHOLD:
                logger.warning('Libtorrent slow loop for {} took {:.3f}', self._name, time_taken)
            await asyncio.sleep(max(0, params.LOOP_INTERVAL - time_taken))

    async def _process_alerts(self, shutting_down):
        await self._exec(self._session.process_alerts, shutting_down)

    async def _post_torrent_updates(self):
        await self._exec(self._session.post_torrent_updates)

    async def _periodic_resume_save(self):
        await self._exec(self._session.all_torrents_save_resume_data, False)

    async def _update_session_stats(self):
        await self._exec(self._session.post_session_stats)

    async def shutdown(self):
        start = time.time()
        logger.debug('Initiating libtorrent shutdown')
        await self._exec(self._session.pause)
        logger.debug('Paused session in {}.', time.time() - start)

        start = time.time()
        logger.debug("Triggering all torrents save resume before shutdown.")
        await self._exec(self._session.all_torrents_save_resume_data, True)
        await self._process_alerts(shutting_down=True)  # Used to populate _num_waiting_for_resume_data
        logger.debug('Waiting for save resume data to complete. Running alert poll loop.')
        wait_start = time.time()
        while self._num_waiting_for_resume_data:
            logger.debug('Still waiting for {} resume data.', self._num_waiting_for_resume_data)
            await self._process_alerts(shutting_down=True)
            await asyncio.sleep(params.LOOP_INTERVAL)
            if time.time() - wait_start > params.SHUTDOWN_TIMEOUT:
                raise LibtorrentClientException('Shutdown timeout reached with {} remaining.'.format(
                    self._num_waiting_for_resume_data))
        logger.info('Saving data completed in {}, deallocating session.', time.time() - start)

        # This will dealloc the session object, which takes time
        def _dealloc_session(self):
            self._session = None

        await self._exec(_dealloc_session, self)
        logger.info('Session destroyed.')

    def get_info_dict(self):
        data = super().get_info_dict()
        data.update({
            'state_path': self.config.state_path,
        })
        return data

    def get_debug_dict(self):
        data = super().get_debug_dict()
        data.update({
            'metrics': dict(sorted(self._metrics.items())) if self._metrics else None,
            # 'settings': dict(sorted(self._session.get_settings().items())),
            'timer_stats': self._timer_stats,
        })
        return data

    async def add_torrent(self, torrent_file, download_path, name):
        logger.debug('Adding torrent to {}', download_path)
        try:
            data = await self._exec(
                self._session.add_torrent,
                torrent_file,
                download_path,
                name,
            )
        except Exception as exc:
            if str(exc) == 'torrent already exists in session':
                raise TorrentAlreadyAddedException()
            else:
                raise
        batch = TorrentBatchUpdate()
        batch.added[data['info_hash']] = data
        self._orchestrator.on_torrent_batch_update(self, batch)
        return data
    
    async def force_reannounce(self, info_hash):
        await self._exec(self._session.force_reannounce, info_hash)

    async def force_recheck(self, info_hash):
        await self._exec(self._session.force_recheck, info_hash)

    async def move_data(self, info_hash, download_path):
        await self._exec(self._session.move_data, info_hash, download_path)

    async def pause_torrent(self, info_hash):
        data = await self._exec(self._session.pause_torrent, info_hash)
        batch = TorrentBatchUpdate()
        batch.updated[data['info_hash']] = data
        self._orchestrator.on_torrent_batch_update(self, batch)

    async def resume_torrent(self, info_hash):
        await self._exec(self._session.resume_torrent, info_hash)
        
    async def rename_torrent(self, info_hash, name):
        await self._exec(self._session.rename_torrent, info_hash, name)

    async def remove_torrent(self, info_hash):
        await self._exec(self._session.remove_torrent, info_hash)
