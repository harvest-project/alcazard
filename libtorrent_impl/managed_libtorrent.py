import asyncio
import logging
import multiprocessing
import time
import traceback
from asyncio import CancelledError
from collections import Counter, defaultdict
from concurrent.futures.thread import ThreadPoolExecutor

import libtorrent

from alcazar_logging import BraceAdapter
from clients import Manager, PeriodicTaskInfo, TorrentAlreadyAddedException
from error_manager import Severity
from libtorrent_impl import params
from libtorrent_impl.session_stats import LibtorrentSessionStats
from libtorrent_impl.torrent_state import LibtorrentTorrentState
from libtorrent_impl.utils import format_libtorrent_endpoint, LibtorrentClientException
from models import ManagedLibtorrentConfig, LibtorrentTorrent, DB
from utils import chunks, timezone_now

if __debug__:
    import pyximport

    pyximport.install()

logger = BraceAdapter(logging.getLogger(__name__))

if not 'profile' in globals():
    globals()['profile'] = lambda fn: fn


def alert_cb_profile(fn):
    def inner(self, alert):
        name = fn.__name__
        start = time.time()
        fn(self, alert)
        self._alert_counts[name] += 1
        self._alert_cumul_time[name] += time.time() - start

    if __debug__:
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
        self.__session = None
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
        # Number of initial torrents remaining to be added
        self._initial_torrents_remaining = None

        # Counters for when the session is started, so that we can add libtorrent's session stats to those
        self.start_total_downloaded = instance_config.total_downloaded
        self.start_total_uploaded = instance_config.total_uploaded

        self._periodic_tasks.append(PeriodicTaskInfo(self._post_torrent_updates, params.POST_UPDATES_INTERVAL))
        self._save_resume_data_task = PeriodicTaskInfo(self._periodic_resume_save, params.SAVE_RESUME_DATA_INTERVAL)
        self._periodic_tasks.append(self._save_resume_data_task)
        self._periodic_tasks.append(
            PeriodicTaskInfo(self._update_session_stats_async, params.UPDATE_SESSION_STATS_INTERVAL))

        self._alert_counts = defaultdict(int)
        self._alert_cumul_time = defaultdict(int)

    @property
    def peer_port(self):
        return self._session.listen_port(),

    def launch(self):
        super().launch()

        self._peer_port = self._orchestrator.grab_peer_port()

        if __debug__:
            logger.debug('Received peer_port={} for {}', self._peer_port, self._name)

        # Reset the timer for saving fast resume data when launched, no need to do it immediately.
        self._save_resume_data_task.last_run_at = time.time()

        settings = params.get_session_settings(self._peer_port, self.config.is_dht_enabled)
        self._session = libtorrent.session(settings)

        from .speedups import session
        import Cython.Compiler.Options
        Cython.Compiler.Options.annotate = True
        self.__session = session.LibtorrentSession(
            db_path=self.config.db_path,
            config_id=self.instance_config.id,
            listen_interfaces='0.0.0.0:{0},[::]:{0}'.format(self._peer_port),
            enable_dht=self.config.is_dht_enabled,
        )

        asyncio.ensure_future(self._load_initial_torrents())
        asyncio.ensure_future(self._loop())

    @profile
    def __load_initial_torrents(self, id_batch):
        if __debug__:
            logger.debug('Loading initial batch of {} torrents.', len(id_batch))

        torrents = list(LibtorrentTorrent.select().where(LibtorrentTorrent.id.in_(id_batch)))
        for torrent in torrents:
            self._libtorrent_torrent_by_info_hash[torrent.info_hash] = torrent
            self._add_torrent(
                torrent=torrent.torrent_file,
                download_path=torrent.download_path,
                async_add=True,
                name=torrent.name,
                resume_data=torrent.resume_data,
            )
            # We will not need the torrent_file anymore and the resume_data will be regenerated for saving
            torrent.torrent_file = None
            torrent.resume_data = None
            self._initial_torrents_remaining -= 1

    @profile
    async def _load_initial_torrents(self):
        logger.info('Starting initial torrent load.')
        start = time.time()
        ids = [i[0] for i in LibtorrentTorrent.select(LibtorrentTorrent.id).where(
            LibtorrentTorrent.libtorrent == self.instance_config).tuples()]
        self._initial_torrents_remaining = len(ids)
        executor = ThreadPoolExecutor(multiprocessing.cpu_count())
        tasks = []
        event_loop = asyncio.get_event_loop()
        for batch in chunks(ids, params.INITIAL_TORRENT_LOAD_BATCH_SIZE):
            tasks.append(event_loop.run_in_executor(executor, self.__load_initial_torrents, batch))
        await asyncio.gather(*tasks)
        executor.shutdown()
        logger.info('Completed initial torrent load in {}.', time.time() - start)

    @profile
    async def _loop(self):
        while True:
            start = time.time()

            try:
                await self._run_periodic_tasks()
                await self._process_alerts_async()
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

    @alert_cb_profile
    @profile
    def _on_alert_torrent_finished(self, alert):
        if not self._initialized:
            return

        info_hash = str(alert.handle.info_hash())
        torrent_state = self._torrent_states[info_hash]

        if __debug__:
            logger.debug('Update torrent finished for {}', info_hash)

        self._save_torrents_resume_data([torrent_state], True)

    @alert_cb_profile
    @profile
    def _on_alert_state_update(self, alert):
        logger.info('Received state updates for {} torrents.', len(alert.status))
        for status in alert.status:
            info_hash = str(status.info_hash)
            if __debug__:
                logger.debug('Update state update for {}.', status.info_hash)
            torrent_state = self._torrent_states[info_hash]
            if torrent_state.update_from_status(status):
                self._orchestrator.on_torrent_updated(torrent_state)

    def __on_resume_data_completed(self, info_hash):
        self._info_hashes_waiting_for_resume_data_save.discard(info_hash)

    @alert_cb_profile
    @profile
    def _on_alert_tracker_announce(self, alert):
        info_hash = str(alert.handle.info_hash())
        if __debug__:
            logger.debug('Tracker announce for {}', info_hash)
        try:
            torrent_state = self._torrent_states[info_hash]
        except KeyError:  # Sometimes we receive updates for torrents that are now deleted
            if __debug__:
                logger.debug('Received tracker reply from missing torrent.')
            return
        torrent_state.tracker_state = LibtorrentTorrentState.TRACKER_ANNOUNCING

    @alert_cb_profile
    @profile
    def _on_alert_tracker_reply(self, alert):
        info_hash = str(alert.handle.info_hash())
        if __debug__:
            logger.debug('Tracker reply for {}', info_hash)
        try:
            torrent_state = self._torrent_states[info_hash]
        except KeyError:  # Sometimes we receive updates for torrents that are now deleted
            if __debug__:
                logger.debug('Received tracker reply from missing torrent.')
            return
        if torrent_state.update_tracker_success():
            self._orchestrator.on_torrent_updated(torrent_state)

    @alert_cb_profile
    @profile
    def _on_alert_tracker_error(self, alert):
        info_hash = str(alert.handle.info_hash())
        if __debug__:
            logger.debug('Tracker error for {}', info_hash)
        try:
            torrent_state = self._torrent_states[info_hash]
        except KeyError:  # Sometimes we receive updates for torrents that are now deleted
            if __debug__:
                logger.debug('Received tracker reply from missing torrent.')
            return
        if torrent_state.update_tracker_error(alert):
            self._orchestrator.on_torrent_updated(torrent_state)

    @alert_cb_profile
    @profile
    def _on_alert_save_resume_data(self, alert):
        info_hash = str(alert.handle.info_hash())
        if __debug__:
            logger.debug('Received fast resume data for {}', info_hash)
        self.__on_resume_data_completed(info_hash)

        torrent_state = self._torrent_states[info_hash]
        torrent_state.db_torrent.resume_data = libtorrent.bencode(alert.resume_data)
        torrent_state.db_torrent.save(only=(LibtorrentTorrent.resume_data,))
        # Save memory after save, since we'll not need that at all
        torrent_state.db_torrent.resume_data = None

    @alert_cb_profile
    @profile
    def _on_alert_save_resume_data_failed(self, alert):
        info_hash = str(alert.handle.info_hash())
        logger.error('Received fast resume data FAILED for {}', info_hash)
        self.__on_resume_data_completed(info_hash)

    @profile
    def _save_torrents_resume_data(self, torrent_states, flush_disk_cache):
        logger.info(
            'Triggering save_resume_data for {} torrents, flush={}',
            'all' if torrent_states is None else str(len(torrent_states)),
            flush_disk_cache,
        )
        flags = libtorrent.save_resume_flags_t.flush_disk_cache if flush_disk_cache else 0

        if torrent_states is None:
            torrent_states = self._torrent_states.values()

        skipped = 0
        for torrent_state in torrent_states:
            # if torrent_state.handle.need_save_resume_data():
            if __debug__:
                logger.debug('Requesting resume data for {}', torrent_state.info_hash)
            self._info_hashes_waiting_for_resume_data_save.add(torrent_state.info_hash)
            torrent_state.handle.save_resume_data(flags)
        # else:
        #     skipped += 1
        if __debug__:
            logger.debug('Skipped saving resume data for {} torrents - not needed.', skipped)

    @alert_cb_profile
    def _on_alert_listen_succeeded(self, alert):
        key, _ = format_libtorrent_endpoint(alert.endpoint)
        self._error_manager.clear_error(key, convert_errors_to_warnings=False)

    @alert_cb_profile
    def _on_alert_listen_failed(self, alert):
        key, readable_name = format_libtorrent_endpoint(alert.endpoint)
        self._error_manager.add_error(Severity.ERROR, key, 'Failed to listen on {}'.format(readable_name))

    @alert_cb_profile
    @profile
    def _on_alert_session_stats(self, alert):
        self._metrics = dict(alert.values)

    @profile
    def __torrent_handle_added(self, status, *, torrent_file=None, download_path=None):
        """
        Executed either form an alert or from synchronous torrent add to update internal state for the new torrent.

        :param info_hash: info_hash of the added torrent
        :param handle: libtorrent.torrent_handle of the added torrent
        :param torrent_file: Only passed during the initial add, so that the LibtorrenTorrent can be created
        :return: The LibtorrentTorrentState of the newly added torrent
        """
        info_hash = str(status.info_hash)
        db_torrent = self._libtorrent_torrent_by_info_hash.pop(info_hash, None)

        completed_loading = (
                not self._initialized and
                self._initial_torrents_remaining == 0 and
                not self._libtorrent_torrent_by_info_hash
        )
        if completed_loading:
            self._initialize_time_seconds = (timezone_now() - self._launch_datetime).total_seconds()
            self._initialized = True

        torrent_state = LibtorrentTorrentState(
            manager=self,
            status=status,
            torrent_file=torrent_file,
            download_path=download_path,
            db_torrent=db_torrent,
        )
        self._torrent_states[torrent_state.info_hash] = torrent_state
        self._orchestrator.on_torrent_added(torrent_state)
        return torrent_state

    @profile
    def _on_alert_add_torrent(self, alert):
        pass

    @alert_cb_profile
    @profile
    def _on_alert_torrent_added(self, alert):
        status = alert.handle.status(0)
        info_hash = str(status.info_hash)
        logger.debug('Received torrent_added for {}', info_hash)
        if info_hash in self._torrent_states:
            self._error_manager.add_error(
                severity=Severity.ERROR,
                key=params.ERROR_KEY_ALREADY_ADDED,
                message='Got alert_torrent_added, but torrent is already in _torrent_states',
            )
        self.__torrent_handle_added(status)

    @alert_cb_profile
    @profile
    def _on_alert_torrent_removed(self, alert):
        info_hash = str(alert.info_hash)
        torrent_state = self._torrent_states[info_hash]
        torrent_state.delete()
        del self._torrent_states[info_hash]
        self._orchestrator.on_torrent_removed(self, info_hash)

    def _process_alerts_sync(self):
        alerts = self._session.pop_alerts()
        if not len(alerts):
            return
        logger.info('Received {} alerts', len(alerts))
        for alerts_batch in chunks(alerts, params.ALERT_BATCH_SIZE):
            self._process_alerts_batch(alerts_batch)

    async def _process_alerts_async(self):
        """
        Like _process_alerts but adds async sleep between batches, so we leave time for other tasks on the event loop
        in case of large alert batches, like saving resume files.
        """

        alerts = self._session.pop_alerts()
        if not len(alerts):
            return
        logger.info('Received {} alerts', len(alerts))
        for alerts_batch in chunks(alerts, params.ALERT_BATCH_SIZE):
            self._process_alerts_batch(alerts_batch)
            await asyncio.sleep(params.ALERT_BATCH_SLEEP)

    @DB.atomic()
    @profile
    def _process_alerts_batch(self, alerts):
        if __debug__:
            logger.debug('Processing batch of {} alerts', len(alerts))

        for a in alerts:
            try:
                # print(type(a))
                # print(a.what())
                # print(a.message())
                # print()

                # Sort list by frequency for performance
                if isinstance(a, libtorrent.state_update_alert):
                    self._on_alert_state_update(a)
                elif isinstance(a, libtorrent.torrent_added_alert):
                    self._on_alert_torrent_added(a)
                elif isinstance(a, libtorrent.add_torrent_alert):
                    self._on_alert_add_torrent(a)
                elif isinstance(a, libtorrent.tracker_announce_alert):
                    self._on_alert_tracker_announce(a)
                elif isinstance(a, libtorrent.tracker_reply_alert):
                    self._on_alert_tracker_reply(a)
                elif isinstance(a, libtorrent.tracker_error_alert):
                    self._on_alert_tracker_error(a)
                elif isinstance(a, libtorrent.save_resume_data_alert):
                    self._on_alert_save_resume_data(a)
                elif isinstance(a, libtorrent.torrent_finished_alert):
                    self._on_alert_torrent_finished(a)
                elif isinstance(a, libtorrent.torrent_removed_alert):
                    self._on_alert_torrent_removed(a)
                elif isinstance(a, libtorrent.session_stats_alert):
                    self._on_alert_session_stats(a)
                elif isinstance(a, libtorrent.listen_succeeded_alert):
                    self._on_alert_listen_succeeded(a)
                elif isinstance(a, libtorrent.listen_failed_alert):
                    self._on_alert_listen_failed(a)
            except CancelledError:
                break
            except Exception:
                alert_type_name = type(a).__name__
                message = 'Error processing alert of type {}'.format(alert_type_name)
                self._error_manager.add_error(
                    Severity.ERROR,
                    params.ERROR_KEY_ALERT_PROCESSING.format(alert_type_name),
                    message,
                    traceback.format_exc(),
                )
                logger.exception(message)

    async def _post_torrent_updates(self):
        self._session.post_torrent_updates()

    async def _periodic_resume_save(self):
        self._save_torrents_resume_data(None, False)

    async def _update_session_stats_async(self):
        self._update_session_stats_sync()

    def _update_session_stats_sync(self):
        self._session.post_session_stats()

        lt_status = self._session.status()
        self._session_stats = LibtorrentSessionStats(
            torrent_count=len(self._torrent_states),
            downloaded=self.start_total_downloaded + lt_status.total_payload_download,
            uploaded=self.start_total_uploaded + lt_status.total_payload_upload,
            download_rate=lt_status.payload_download_rate,
            upload_rate=lt_status.payload_upload_rate,
        )
        self.instance_config.total_downloaded = self._session_stats.downloaded
        self.instance_config.total_uploaded = self._session_stats.uploaded
        self.instance_config.save(only=(
            ManagedLibtorrentConfig.total_downloaded,
            ManagedLibtorrentConfig.total_uploaded,
        ))

    def shutdown(self):
        start = time.time()
        if __debug__:
            logger.debug('Initiating libtorrent shutdown')
        self._session.pause()
        if __debug__:
            logger.debug('Paused session in {}.', time.time() - start)

        start = time.time()
        self._save_torrents_resume_data(None, True)
        if __debug__:
            logger.debug('Waiting for save resume data to complete. Running alert poll loop.')
        wait_start = time.time()
        while self._info_hashes_waiting_for_resume_data_save:
            self._process_alerts_sync()  # Process as fast as possible
            time.sleep(params.LOOP_INTERVAL)
            if time.time() - wait_start > params.SHUTDOWN_TIMEOUT:
                raise LibtorrentClientException('Shutdown timeout reached.')
        logger.info('Saving data completed in {}, session stopped.', time.time() - start)

        self._update_session_stats_sync()

        self._session = None

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
            'metrics': self._metrics,
            'settings': dict(sorted(self._session.get_settings().items())),
            'alert_counts': self._alert_counts,
            'alert_cumul_time': self._alert_cumul_time,
        })
        return data

    @profile
    def _add_torrent(self, torrent, download_path, name, *, async_add, resume_data):
        add_params = params.get_torrent_add_params(torrent, download_path, name, resume_data)

        if async_add:
            self._session.async_add_torrent(add_params)
        else:
            handle = self._session.add_torrent(add_params)
            status = handle.status(0)
            if str(status.info_hash) in self._torrent_states:
                raise TorrentAlreadyAddedException()
            torrent_state = self.__torrent_handle_added(
                status=status,
                torrent_file=torrent,
                download_path=download_path,
            )
            return torrent_state

    async def add_torrent(self, torrent, download_path, name):
        if __debug__:
            logger.debug('Adding torrent to {}', download_path)
        return self._add_torrent(
            torrent=torrent,
            download_path=download_path,
            name=name,
            async_add=False,
            resume_data=None,
        )

    async def delete_torrent(self, info_hash):
        torrent_state = self._torrent_states[info_hash]
        self._session.remove_torrent(torrent_state.handle, libtorrent.options_t.delete_files)
