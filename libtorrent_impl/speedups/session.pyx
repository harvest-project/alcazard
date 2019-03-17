# cython: language_level=3
import time

from cython.operator cimport dereference as deref
from libc.stdint cimport int64_t, uint64_t
from libcpp cimport bool as cbool
from libcpp.string cimport string
from libcpp.vector cimport vector
from libcpp.utility cimport pair
from libcpp.memory cimport shared_ptr
from libcpp.unordered_map cimport unordered_map

from libtorrent_impl import params
from models import ManagedLibtorrentConfig
from utils import timezone_now
from .libtorrent cimport to_hex

import logging
from clients import SessionStats, TorrentBatchUpdate

logger = logging.getLogger(__name__)

cdef extern from "Utils.hpp" namespace "Logger":
    cdef enum Level:
        CRITICAL
        ERROR
        WARNING
        INFO
        DEBUG

    cdef void set_level(Level level)

cdef extern from "SessionWrapper.hpp":
    cdef cppclass TorrentState:
        string info_hash
        int status
        string name;
        string download_path;
        int64_t size;
        int64_t downloaded;
        int64_t uploaded;
        int64_t download_rate;
        int64_t upload_rate;
        double progress;
        string error;
        string tracker_error;

    ctypedef struct TimerStat:
        int count
        double total_seconds

    cdef cppclass BatchTorrentUpdate:
        vector[shared_ptr[TorrentState]] added
        vector[shared_ptr[TorrentState]] updated
        vector[string] removed

        unordered_map[string, uint64_t] metrics;
        unordered_map[string, TimerStat] timer_stats;

        int num_waiting_for_resume_data

    cdef cppclass SessionWrapper:
        unordered_map[string, shared_ptr[TorrentState]] torrent_states

        SessionWrapper(
                string db_path,
                int config_id,
                string listen_interfaces,
                cbool enable_dht,
        ) nogil except +

        void load_initial_torrents() nogil except +
        void async_add_torrent(string bytes, string download_path, string *name, string *resume_data) nogil except +
        void post_torrent_updates() nogil except +
        void pause() nogil except +
        int listen_port() nogil except +
        BatchTorrentUpdate process_alerts() nogil except +
        void post_session_stats() nogil except +
        void all_torrents_save_resume_data(cbool flush_cache) nogil except +

cdef calc_dict_rate(old_dict, new_dict, key):
    if not old_dict:
        return 0
    return int((new_dict[key] - old_dict[key]) / params.UPDATE_SESSION_STATS_INTERVAL)

cdef class LibtorrentSession:
    cdef:
        orchestrator
        manager
        instance_config
        start_total_downloaded
        start_total_uploaded
        SessionWrapper *wrapper
        str name

    def __init__(self, manager, str db_path, int config_id, str listen_interfaces, cbool enable_dht):
        cdef:
            string c_db_path = db_path.encode()
            string c_listen_interfaces = listen_interfaces.encode()

        set_level(<Level><int>logging.getLogger('').level)

        self.orchestrator = manager._orchestrator
        self.manager = manager
        self.instance_config = manager.instance_config
        self.name = manager.name

        # Counters for when the session is started, so that we can add libtorrent's session stats to those
        self.start_total_downloaded = self.instance_config.total_downloaded
        self.start_total_uploaded = self.instance_config.total_uploaded

        with nogil:
            self.wrapper = new SessionWrapper(
                c_db_path,
                config_id,
                c_listen_interfaces,
                enable_dht,
            )

    def __dealloc__(self):
        with nogil:
            del self.wrapper

    def post_torrent_updates(self):
        with nogil:
            self.wrapper.post_torrent_updates()

    def pause(self):
        with nogil:
            self.wrapper.pause()

    cdef dict torrent_state_to_dict(self, shared_ptr[TorrentState] state):
        return {
            'info_hash': to_hex(deref(state).info_hash).decode(),
            'client': self.name,
            'status': deref(state).status,
            'name': deref(state).name.decode(),
            'download_path': deref(state).download_path.decode(),
            'size': deref(state).size,
            'downloaded': deref(state).downloaded,
            'uploaded': deref(state).uploaded,
            'download_rate': deref(state).download_rate,
            'upload_rate': deref(state).upload_rate,
            'progress': deref(state).progress,
            'error': deref(state).error if deref(state).error.size() else None,
            'tracker_error': deref(state).tracker_error if deref(state).tracker_error.size() else None,
            'date_added': None,
        }

    cdef void _update_manager_session_stats(self, dict prev_metrics, dict new_metrics) except *:
        cdef:
            int payload_download = new_metrics['net.recv_payload_bytes[counter]']
            int payload_upload = new_metrics['net.sent_payload_bytes[counter]']

        self.manager._session_stats = SessionStats(
            torrent_count=new_metrics['ses.num_loaded_torrents[gauge]'],
            downloaded=self.start_total_downloaded + payload_download,
            uploaded=self.start_total_uploaded + payload_upload,
            download_rate=calc_dict_rate(prev_metrics, new_metrics, 'net.recv_payload_bytes[counter]'),
            upload_rate=calc_dict_rate(prev_metrics, new_metrics, 'net.sent_payload_bytes[counter]'),
        )

        updated = (
                self.instance_config.total_downloaded != self.manager._session_stats.downloaded or
                self.instance_config.total_uploaded != self.manager._session_stats.uploaded
        )
        if updated:
            logger.debug('Updating session stats in DB.')
            self.instance_config.total_downloaded = self.manager._session_stats.downloaded
            self.instance_config.total_uploaded = self.manager._session_stats.uploaded
            self.instance_config.save(only=(
                ManagedLibtorrentConfig.total_downloaded,
                ManagedLibtorrentConfig.total_uploaded,
            ))

    cdef void _update_session_metrics(self, BatchTorrentUpdate update) except *:
        cdef:
            pair[string, TimerStat] timer_stat
            pair[string, uint64_t] metric_stat
            dict timer_stats_dict = {}
            dict metrics_dict = {}

        self.manager._num_waiting_for_resume_data = update.num_waiting_for_resume_data

        if update.timer_stats.size():
            for timer_stat in update.timer_stats:
                timer_stats_dict[timer_stat.first.decode()] = <dict>timer_stat.second
            self.manager._timer_stats = timer_stats_dict

        if update.metrics.size():
            for metric_stat in update.metrics:
                metrics_dict[metric_stat.first.decode()] = metric_stat.second
            prev_metrics = self.manager._metrics
            self.manager._metrics = metrics_dict
            self._update_manager_session_stats(prev_metrics, metrics_dict)

        if not self.manager._initialized and 'initial_torrents_received' in timer_stats_dict:
            self.manager._initialized = True
            self.manager._initialize_time_seconds = (timezone_now() - self.manager._launch_datetime).total_seconds()

    def process_alerts(self):
        cdef:
            BatchTorrentUpdate update
            dict state_dict

            dict added = {}
            dict updated = {}
            set removed = set()

        logger.debug('Processing alerts without gil')
        with nogil:
            update = self.wrapper.process_alerts()

        logger.debug('Updating session metrics')
        self._update_session_metrics(update)

        # Short-circuit empty update batches
        if update.added.size() == 0 and update.updated.size() == 0 and update.removed.size() == 0:
            return None

        logger.debug('Creating batch update')
        for state in update.added:
            state_dict = self.torrent_state_to_dict(state)
            added[state_dict['info_hash']] = state_dict
        for state in update.updated:
            state_dict = self.torrent_state_to_dict(state)
            updated[state_dict['info_hash']] = state_dict
        for info_hash in update.removed:
            removed.add(info_hash)

        logger.debug('Firing batch')
        self.orchestrator.on_torrent_batch_update(self.manager, TorrentBatchUpdate(added, updated, removed))
        logger.debug('Batch is processed')

    def async_add_torrent(self, bytes torrent, str download_path, str name, bytes resume_data):
        cdef:
            string c_torrent = torrent
            string c_download_path = download_path.encode()
            string c_name
            string c_resume_data
        if name:
            c_name = name
        if resume_data:
            c_resume_data = resume_data

        with nogil:
            self.wrapper.async_add_torrent(
                c_torrent,
                c_download_path,
                &c_name if name is not None else NULL,
                &c_resume_data if resume_data is not None else NULL,
            )

    def post_session_stats(self):
        self.wrapper.post_session_stats()

    def status(self):
        pass

    def load_initial_torrents(self):
        with nogil:
            self.wrapper.load_initial_torrents()

    def all_torrents_save_resume_data(self, flush_cache):
        cdef cbool c_flush_cache = flush_cache

        with nogil:
            self.wrapper.all_torrents_save_resume_data(c_flush_cache)
