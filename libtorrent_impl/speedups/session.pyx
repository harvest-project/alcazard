# cython: language_level=3

from libc.stdio cimport printf
from libc.stdint cimport int64_t
from libcpp cimport bool as cbool
from libcpp.string cimport string
from libcpp.vector cimport vector
from libcpp.unordered_map cimport unordered_map
from .libtorrent cimport to_hex, session_status

import logging
from clients import SessionStats

logger = logging.getLogger(__name__)

cdef extern from "SessionWrapper.hpp":
    cdef cppclass TorrentState:
        string info_hash
        int status
        string download_path;
        int64_t size;
        int64_t downloaded;
        int64_t uploaded;
        int64_t download_rate;
        int64_t upload_rate;
        double progress;
        string error;
        string tracker_error;

    cdef cppclass BatchTorrentUpdate:
        vector[TorrentState*] added
        vector[TorrentState*] updated
        vector[string] deleted

    cdef cppclass SessionWrapper:
        unordered_map[string, TorrentState*] torrent_states

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
        session_status status() nogil except +

def enc_str(s):
    return s.encode() if s else None

cdef dict torrent_state_to_dict(TorrentState *state):
    return {
        'info_hash': to_hex(state.info_hash).decode(),
        'status': state.status,
        'download_path': state.download_path.decode(),
        'size': state.size,
        'downloaded': state.downloaded,
        'uploaded': state.uploaded,
        'download_rate': state.download_rate,
        'upload_rate': state.upload_rate,
        'progress': state.progress,
        'error': state.error if state.error.size() else None,
        'tracker_error': state.tracker_error if state.tracker_error.size() else None,
    }

cdef class LibtorrentSession:
    cdef:
        orchestrator
        manager
        instance_config
        start_total_downloaded
        start_total_uploaded
        SessionWrapper *wrapper

    def __init__(self, manager, str db_path, int config_id, str listen_interfaces, cbool enable_dht):
        cdef:
            string c_db_path = db_path.encode()
            string c_listen_interfaces = listen_interfaces.encode()

        self.orchestrator = manager._orchestrator
        self.manager = manager
        self.instance_config = manager.instance_config

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
        del self.wrapper

    def post_torrent_updates(self):
        with nogil:
            self.wrapper.post_torrent_updates()

    def pause(self):
        with nogil:
            self.wrapper.pause()

    def process_alerts(self):
        cdef:
            BatchTorrentUpdate update
            dict state_dict

        logger.info('Processing alerts without gil')
        with nogil:
            update = self.wrapper.process_alerts()

        logger.info('Processing batch')
        for state in update.added:
            state_dict = torrent_state_to_dict(state)
            self.orchestrator.on_torrent_added(self.manager, state_dict)
        for state in update.updated:
            state_dict = torrent_state_to_dict(state)
            self.orchestrator.on_torrent_updated(self.manager, state_dict)
        for info_hash in update.deleted:
            self.orchestrator.on_torrent_deleted(self.manager, info_hash)

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
        pass

    def status(self):
        pass

    def listen_port(self):
        return self.wrapper.listen_port()

    def get_session_stats(self):
        cdef:
            session_status status = self.wrapper.status()

        return SessionStats(
            torrent_count=self.wrapper.torrent_states.size(),
            downloaded=self.start_total_downloaded + status.total_payload_download,
            uploaded=self.start_total_uploaded + status.total_payload_upload,
            download_rate=status.payload_download_rate,
            upload_rate=status.payload_upload_rate,
        )

    def load_initial_torrents(self):
        with nogil:
            self.wrapper.load_initial_torrents()
