import asyncio
import logging
import os
import time
import traceback
from asyncio import CancelledError
from collections import Counter

import libtorrent

from clients import Manager, PeriodicTaskInfo, TorrentAlreadyAddedException
from error_manager import Severity
from libtorrent_impl import params
from libtorrent_impl.params import POST_UPDATES_INTERVAL, SAVE_RESUME_DATA_INTERVAL, UPDATE_SESSION_STATS_INTERVAL
from libtorrent_impl.session_stats import LibtorrentSessionStats
from libtorrent_impl.torrent_state import LibtorrentTorrentState
from libtorrent_impl.utils import format_libtorrent_endpoint, LibtorrentClientException
from models import ManagedLibtorrentConfig, LibtorrentTorrent, DB
from utils import chunks

logger = logging.getLogger(__name__)


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
        # Has this instance added all of its torrents to the session
        self._initialized = False
        # Metrics refreshed together with session stats
        self._metrics = None

        # Counters for when the session is started, so that we can add libtorrent's session stats to those
        self.start_total_downloaded = instance_config.total_downloaded
        self.start_total_uploaded = instance_config.total_uploaded

        self._periodic_tasks.append(PeriodicTaskInfo(self._post_torrent_updates, POST_UPDATES_INTERVAL))
        self._save_resume_data_task = PeriodicTaskInfo(self._periodic_resume_save, SAVE_RESUME_DATA_INTERVAL)
        self._periodic_tasks.append(self._save_resume_data_task)
        self._periodic_tasks.append(PeriodicTaskInfo(self._update_session_stats, UPDATE_SESSION_STATS_INTERVAL))

    @property
    def peer_port(self):
        return self._session.listen_port(),

    def launch(self):
        logger.debug('Launching {}'.format(self._name))

        self._peer_port = self._orchestrator.grab_peer_port()
        logger.debug('Received peer_port={} for {}'.format(self._peer_port, self._name))

        # Reset the timer for saving fast resume data when launched, no need to do it immediately.
        self._save_resume_data_task.last_run_at = time.time()

        settings = params.get_session_settings(self._peer_port, self.config.is_dht_enabled)
        self._session = libtorrent.session(settings)

        asyncio.ensure_future(self._loop())
        asyncio.ensure_future(self._load_initial_torrents())

    async def __load_initial_torrents(self, id_batch):
        logger.debug('Loading initial batch of {} torrents.'.format(len(id_batch)))
        torrents = list(LibtorrentTorrent.select().where(LibtorrentTorrent.id.in_(id_batch)))
        for torrent in torrents:
            self._libtorrent_torrent_by_info_hash[torrent.info_hash] = torrent
            self._add_torrent(
                torrent=torrent.torrent_file,
                download_path=torrent.download_path,
                async_add=True,
                resume_data=torrent.resume_data,
            )
            # We will not need the torrent_file anymore and the resume_data will be regenerated for saving
            torrent.torrent_file = None
            torrent.resume_data = None

    async def _load_initial_torrents(self):
        start = time.time()
        ids = list(LibtorrentTorrent.select(LibtorrentTorrent.id).tuples())
        for batch in chunks(ids, 100):
            await self.__load_initial_torrents(batch)
            await asyncio.sleep(0.5)
        logger.info('Completed initial torrent load in {}.'.format(time.time() - start))

    async def _loop(self):
        while True:
            start = time.time()

            try:
                await self._run_periodic_tasks()
                self._process_alerts()
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
            if time_taken > 0.1:
                logger.info('Libtorrent slow loop for {} took {:.3f}'.format(self._name, time_taken))
            await asyncio.sleep(max(0, params.LOOP_INTERVAL - time_taken))

    def _on_alert_torrent_finished(self, alert):
        status = alert.handle.status()
        info_hash = str(status.info_hash)
        torrent_state = self._torrent_states[info_hash]
        logger.debug('Update torrent finished for {}'.format(info_hash))
        # Copied explanation from Deluge:
        # Only save resume data if it was actually downloaded something. Helps
        # on startup with big queues with lots of seeding torrents. Libtorrent
        # emits alert_torrent_finished for them, but there seems like nothing
        # worth really to save in resume data, we just read it up in
        # self.load_state().
        if status.total_payload_download:
            self._save_torrents_resume_data([torrent_state], True)

    def _on_alert_state_update(self, alert):
        for status in alert.status:
            info_hash = str(status.info_hash)
            logger.debug('Update state update for {}'.format(status.info_hash))
            torrent_state = self._torrent_states[info_hash]
            if torrent_state.update_from_status(status):
                self._orchestrator.on_torrent_updated(torrent_state)

    def __on_resume_data_completed(self, info_hash):
        self._info_hashes_waiting_for_resume_data_save.discard(info_hash)

    def _on_alert_tracker_announce(self, alert):
        info_hash = str(alert.handle.info_hash())
        logger.debug('Tracker announce for {}'.format(info_hash))
        try:
            torrent_state = self._torrent_states[info_hash]
        except KeyError:  # Sometimes we receive updates for torrents that are now deleted
            logger.debug('Received tracker reply from missing torrent.')
            return
        torrent_state.tracker_state = LibtorrentTorrentState.TRACKER_ANNOUNCING

    def _on_alert_tracker_reply(self, alert):
        info_hash = str(alert.handle.info_hash())
        logger.debug('Tracker reply for {}'.format(info_hash))
        try:
            torrent_state = self._torrent_states[info_hash]
        except KeyError:  # Sometimes we receive updates for torrents that are now deleted
            logger.debug('Received tracker reply from missing torrent.')
            return
        if torrent_state.update_tracker_success():
            self._orchestrator.on_torrent_updated(torrent_state)

    def _on_alert_tracker_error(self, alert):
        info_hash = str(alert.handle.info_hash())
        logger.debug('Tracker error for {}'.format(info_hash))
        try:
            torrent_state = self._torrent_states[info_hash]
        except KeyError:  # Sometimes we receive updates for torrents that are now deleted
            logger.debug('Received tracker reply from missing torrent.')
            return
        if torrent_state.update_tracker_error(alert):
            self._orchestrator.on_torrent_updated(torrent_state)

    def _on_alert_save_resume_data(self, alert):
        info_hash = str(alert.handle.info_hash())
        logger.debug('Received fast resume data for {}'.format(info_hash))
        self.__on_resume_data_completed(info_hash)

        torrent_state = self._torrent_states[info_hash]
        torrent_state.db_torrent.resume_data = libtorrent.bencode(alert.resume_data)
        torrent_state.db_torrent.save(only=(LibtorrentTorrent.resume_data,))
        # Save memory after save, since we'll not need that at all
        torrent_state.db_torrent.resume_data = None

    def _on_alert_save_resume_data_failed(self, alert):
        info_hash = str(alert.handle.info_hash())
        logger.error('Received fast resume data FAILED for {}'.format(info_hash))
        self.__on_resume_data_completed(info_hash)

    def _save_torrents_resume_data(self, torrent_states, flush_disk_cache):
        logger.info('Triggering save_resume_data for {} torrents, flush={}'.format(
            'all' if torrent_states is None else str(len(torrent_states)),
            flush_disk_cache,
        ))
        flags = libtorrent.save_resume_flags_t.flush_disk_cache if flush_disk_cache else 0

        if torrent_states is None:
            torrent_states = self._torrent_states.values()

        skipped = 0
        for torrent_state in torrent_states:
            if torrent_state.handle.need_save_resume_data():
                logger.debug('Requesting resume data for {}'.format(torrent_state.info_hash))
                self._info_hashes_waiting_for_resume_data_save.add(torrent_state.info_hash)
                torrent_state.handle.save_resume_data(flags)
            else:
                skipped += 1
        logger.debug('Skipped saving resume data for {} torrents - not needed.'.format(skipped))

    def _on_alert_listen_succeeded(self, alert):
        key, _ = format_libtorrent_endpoint(alert.endpoint)
        self._error_manager.clear_error(key, convert_errors_to_warnings=False)

    def _on_alert_listen_failed(self, alert):
        key, readable_name = format_libtorrent_endpoint(alert.endpoint)
        self._error_manager.add_error(Severity.ERROR, key, 'Failed to listen on {}'.format(readable_name))

    def _on_alert_session_stats(self, alert):
        self._metrics = dict(alert.values)

    def __torrent_handle_added(self, handle, *, torrent_file=None, download_path=None):
        """

        :param info_hash: info_hash of the added torrent
        :param handle: libtorrent.torrent_handle of the added torrent
        :param torrent_file: Only passed during the initial add, so that the LibtorrenTorrent can be created
        :return:
        """
        info_hash = str(handle.info_hash())
        db_torrent = self._libtorrent_torrent_by_info_hash.pop(info_hash, None)
        if not self._initialized and not self._libtorrent_torrent_by_info_hash:
            self._initialized = True
        torrent_state = LibtorrentTorrentState(
            manager=self,
            handle=handle,
            torrent_file=torrent_file,
            download_path=download_path,
            db_torrent=db_torrent,
        )
        self._torrent_states[torrent_state.info_hash] = torrent_state
        self._orchestrator.on_torrent_added(torrent_state)
        return torrent_state

    def _on_alert_torrent_added(self, alert):
        handle = alert.handle
        info_hash = str(handle.info_hash())
        logger.debug('Received torrent_added for {}'.format(info_hash))
        if info_hash not in self._torrent_states:
            self.__torrent_handle_added(handle)

    def _on_alert_torrent_removed(self, alert):
        info_hash = str(alert.info_hash)
        torrent_state = self._torrent_states[info_hash]
        torrent_state.delete()
        del self._torrent_states[info_hash]
        self._orchestrator.on_torrent_removed(self, info_hash)

    def _process_alerts(self):
        alerts = self._session.pop_alerts()
        if not len(alerts):
            return
        logging.info('Received {} alerts'.format(len(alerts)))
        for alerts_batch in chunks(alerts, 5000):
            logging.debug('Processing batch of {} alerts'.format(len(alerts_batch)))
            with DB.atomic():
                self.__process_alerts(alerts_batch)

    def __process_alerts(self, alerts):
        for a in alerts:
            try:
                # print(type(a))
                # print(a.what())
                # print(a.message())
                # print()

                if isinstance(a, libtorrent.state_update_alert):
                    self._on_alert_state_update(a)
                elif isinstance(a, libtorrent.torrent_finished_alert):
                    self._on_alert_torrent_finished(a)
                elif isinstance(a, libtorrent.tracker_announce_alert):
                    self._on_alert_tracker_announce(a)
                elif isinstance(a, libtorrent.tracker_reply_alert):
                    self._on_alert_tracker_reply(a)
                elif isinstance(a, libtorrent.tracker_error_alert):
                    self._on_alert_tracker_error(a)
                elif isinstance(a, libtorrent.save_resume_data_alert):
                    self._on_alert_save_resume_data(a)
                elif isinstance(a, libtorrent.torrent_added_alert):
                    self._on_alert_torrent_added(a)
                elif isinstance(a, libtorrent.listen_succeeded_alert):
                    self._on_alert_listen_succeeded(a)
                elif isinstance(a, libtorrent.listen_failed_alert):
                    self._on_alert_listen_failed(a)
                elif isinstance(a, libtorrent.torrent_removed_alert):
                    self._on_alert_torrent_removed(a)
                elif isinstance(a, libtorrent.session_stats_alert):
                    self._on_alert_session_stats(a)
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

    async def _update_session_stats(self):
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
        logger.debug('Initiating libtorrent shutdown')
        self._session.pause()
        logger.debug('Paused session in {}.'.format(time.time() - start))

        start = time.time()
        self._save_torrents_resume_data(None, True)
        logger.debug('Waiting for save resume data to complete. Running alert poll loop.')
        wait_start = time.time()
        while self._info_hashes_waiting_for_resume_data_save:
            self._process_alerts()
            time.sleep(params.LOOP_INTERVAL)
            if time.time() - wait_start > params.SHUTDOWN_TIMEOUT:
                raise LibtorrentClientException('Shutdown timeout reached.')
        logger.debug('Saving data completed in {}, session stopped.'.format(time.time() - start))

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
            'torrents_with_errors': len([None for state in self._torrent_states.values() if state.error]),
            'torrent_error_types': Counter([ts.error for ts in self._torrent_states.values()]),
            'torrent_tracker_error_types': Counter([ts.tracker_error for ts in self._torrent_states.values()]),
            'torrent_tracker_statuses': Counter([_get_tracker_status(ts) for ts in self._torrent_states.values()]),
            'metrics': self._metrics,
        })
        data.update(self._error_manager.to_dict())
        return data

    def _add_torrent(self, torrent, download_path, *, async_add, resume_data):
        lt_torrent_info = libtorrent.torrent_info(libtorrent.bdecode(torrent))

        # Temporary workaround until we can tell apart multi-file torrents from torrent_info
        files = lt_torrent_info.files()
        if files.num_files() == 1 and files.file_path(0) == files.file_name(0):
            # Single-file torrent - save it in download_path
            save_path = download_path
        else:
            # Multi-file torrent - save it in parent directory, rename to basename
            save_path = os.path.dirname(download_path)
            files.set_name(os.path.basename(download_path))

        add_params = {
            'ti': lt_torrent_info,
            'save_path': save_path,
            'storage_mode': libtorrent.storage_mode_t.storage_mode_sparse,
            'paused': False,
            'auto_managed': True,
            'duplicate_is_error': True,
            'flags': libtorrent.add_torrent_params_flags_t.default_flags |
                     libtorrent.add_torrent_params_flags_t.flag_update_subscribe,
        }
        if resume_data:
            add_params['resume_data'] = resume_data

        if async_add:
            self._session.async_add_torrent(add_params)
        else:
            handle = self._session.add_torrent(add_params)
            if str(handle.info_hash()) in self._torrent_states:
                raise TorrentAlreadyAddedException()
            torrent_state = self.__torrent_handle_added(
                handle=handle,
                torrent_file=torrent,
                download_path=download_path,
            )
            return torrent_state

    async def add_torrent(self, torrent, download_path):
        logger.debug('Adding torrent to {}'.format(download_path))
        return self._add_torrent(
            torrent=torrent,
            download_path=download_path,
            async_add=False,
            resume_data=None,
        )

    async def delete_torrent(self, info_hash):
        torrent_state = self._torrent_states[info_hash]
        self._session.remove_torrent(torrent_state.handle, libtorrent.options_t.delete_files)
