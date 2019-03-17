import asyncio
import logging
import time
import traceback
from asyncio import CancelledError
from collections import Counter
from concurrent.futures.thread import ThreadPoolExecutor

from alcazar_logging import BraceAdapter
from clients import Manager, PeriodicTaskInfo, TorrentAlreadyAddedException
from error_manager import Severity
from libtorrent_impl import params
from libtorrent_impl.speedups import session
from libtorrent_impl.torrent_state import LibtorrentTorrentState
from libtorrent_impl.utils import LibtorrentClientException
from models import ManagedLibtorrentConfig

logger = BraceAdapter(logging.getLogger(__name__))
enable_debug = logger.isEnabledFor(logging.DEBUG)


def alert_cb_profile(fn):
    def inner(self, alert):
        name = fn.__name__
        start = time.time()
        fn(self, alert)
        self._alert_counts[name] += 1
        self._alert_cumul_time[name] += time.time() - start

    if enable_debug:
        return inner
    else:
        return fn


class ManagedLibtorrent(Manager):
    key = 'managed_libtorrent'
    config_model = ManagedLibtorrentConfig

    def __init__(self, orchestrator, instance_config):
        super().__init__(orchestrator, instance_config)

        self._peer_port = None
        self._session = None
        self._torrent_states = {}
        # Timestamp (float) of when the last torrent updates request was posted.
        self._last_post_updates_request = None
        # Timestamp (float) of when the last resume data save was triggered
        self._last_save_resume_data_request = None
        # Set of info_hashes we're waiting to receive a resume data (failed) alert for.
        # Used in shutdown to wait for all.
        self._info_hashes_waiting_for_resume_data_save = set()
        # Used to cache LibtorrentTorrent model instances that we add during startup to avoid issuing N selects
        self._libtorrent_torrent_by_info_hash = {}
        # Metrics refreshed together with session stats
        self._metrics = None
        # Timer stats from the C++ session manager
        self._timer_stats = None
        # Number of initial torrents remaining to be added
        self._initial_torrents_remaining = None
        # Listen port to be set by the first iteration of update_session_stats
        self._listen_port = None

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

        start = time.time()
        logger.warning("START _EXEC {}", fn.__name__)
        result = await future
        logger.warning("END _EXEC {} TOOK {}", fn.__name__, time.time() - start)
        return result

    @property
    def peer_port(self):
        return self._listen_port

    def launch(self):
        super().launch()

        self._peer_port = self._orchestrator.grab_peer_port()

        if enable_debug:
            logger.debug('Received peer_port={} for {}', self._peer_port, self._name)

        # Reset the timer for saving fast resume data when launched, no need to do it immediately.
        self._save_resume_data_task.last_run_at = time.time()

        self._session = session.LibtorrentSession(
            manager=self,
            db_path=self.config.db_path,
            config_id=self.instance_config.id,
            listen_interfaces='0.0.0.0:{0},[::]:{0}'.format(self._peer_port),
            enable_dht=self.config.is_dht_enabled,
        )

        asyncio.ensure_future(self._loop())
        asyncio.ensure_future(self._load_initial_torrents())

    async def _load_initial_torrents(self):
        logger.info('Starting initial torrent load.')
        start = time.time()
        await self._exec(self._session.load_initial_torrents)
        logger.info('Completed initial torrent load in {}.', time.time() - start)

    async def _loop(self):
        while True:
            start = time.time()

            try:
                await self._run_periodic_tasks()
                await self._process_alerts()
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

    async def _process_alerts(self):
        await self._exec(self._session.process_alerts)

    async def _post_torrent_updates(self):
        await self._exec(self._session.post_torrent_updates)

    async def _periodic_resume_save(self):
        pass  # self._save_torrents_resume_data(None, False)

    async def _update_session_stats(self):
        await self._exec(self._session.post_session_stats)

    async def shutdown(self):
        start = time.time()
        if enable_debug:
            logger.debug('Initiating libtorrent shutdown')
        await self._exec(self._session.pause)
        if enable_debug:
            logger.debug('Paused session in {}.', time.time() - start)

        start = time.time()
        self._save_torrents_resume_data(None, True)
        if enable_debug:
            logger.debug('Waiting for save resume data to complete. Running alert poll loop.')
        wait_start = time.time()
        while self._info_hashes_waiting_for_resume_data_save:
            await self._process_alerts()  # Process as fast as possible
            time.sleep(params.LOOP_INTERVAL)
            if time.time() - wait_start > params.SHUTDOWN_TIMEOUT:
                raise LibtorrentClientException('Shutdown timeout reached.')
        logger.info('Saving data completed in {}, session stopped.', time.time() - start)

        # TODO: This is now very async, we need to wait for the alert
        await self._update_session_stats()
        logger.debug('Final session sync completed, deallocating session.')

        # This will dealloc the session object, which takes time
        def _dealloc_session(self):
            self._session = None

        await self._exec(_dealloc_session, self)
        logger.debug('Session destroyed.')

    def get_info_dict(self):
        data = super().get_info_dict()
        data.update({
            'state_path': self.config.state_path,
        })
        return data

    def get_debug_dict(self):
        def _get_tracker_status(ts):
            return {
                LibtorrentTorrentState.TRACKER_PENDING: 'pending',
                LibtorrentTorrentState.TRACKER_ANNOUNCING: 'announcing',
                LibtorrentTorrentState.TRACKER_SUCCESS: 'success',
                LibtorrentTorrentState.TRACKER_ERROR: 'error',
            }[ts.tracker_status]

        data = super().get_debug_dict()
        data.update({
            'num_torrent_per_state': Counter([ts.state for ts in self._torrent_states.values()]),
            'initial_torrents_remaining': self._initial_torrents_remaining,
            'torrents_with_errors': len([None for state in self._torrent_states.values() if state.error]),
            'torrent_error_types': Counter([ts.error for ts in self._torrent_states.values()]),
            'torrent_tracker_error_types': Counter([ts.tracker_error for ts in self._torrent_states.values()]),
            'torrent_tracker_statuses': Counter([_get_tracker_status(ts) for ts in self._torrent_states.values()]),
            'metrics': dict(sorted(self._metrics.items())) if self._metrics else None,
            # 'settings': dict(sorted(self._session.get_settings().items())),
            'timer_stats': self._timer_stats,
        })
        return data

    async def _add_torrent(self, torrent, download_path, name, *, async_add, resume_data):
        if async_add:
            await self._exec(
                self._session.async_add_torrent,
                torrent,
                download_path,
                name,
                resume_data,
            )
        else:
            add_params = params.get_torrent_add_params(torrent, download_path, name, resume_data)
            handle = await self._exec(self._session.add_torrent)
            status = handle.status()
            if str(status.info_hash) in self._torrent_states:
                raise TorrentAlreadyAddedException()
            torrent_state = self.__torrent_handle_added(
                status=status,
                torrent_file=torrent,
                download_path=download_path,
            )
            return torrent_state

    async def add_torrent(self, torrent, download_path, name):
        if enable_debug:
            logger.debug('Adding torrent to {}', download_path)
        return await self._add_torrent(
            torrent=torrent,
            download_path=download_path,
            name=name,
            async_add=False,
            resume_data=None,
        )

    async def delete_torrent(self, info_hash):
        await self._exec(self._session.remove_torrent, info_hash)
