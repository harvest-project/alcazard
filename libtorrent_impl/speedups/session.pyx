# cython: language_level=3

from libc.stdio cimport printf
from libcpp.vector cimport vector
from cython.operator cimport dereference as deref

from .helpers cimport shared_ptr
from .libtorrent_torrent_info cimport torrent_info, file_storage
from .libtorrent_add_torrent_params cimport add_torrent_params, storage_mode_t, flags_t
from .libtorrent_alert cimport category_t
from .libtorrent_session cimport session
from .libtorrent_settings_pack cimport bool_types, int_types, string_types, settings_pack

DEF MILLION = 10 ** 6

cdef class LibtorrentSession:
    cdef session *_session

    def __init__(self, settings):
        printf('Creating session\n')

        cdef settings_pack pack
        pack.set_str(string_types.user_agent, 'Deluge/{}'.format('1.2.15').encode())
        pack.set_str(string_types.peer_fingerprint, '-DE13F0-'.encode())
        pack.set_int(int_types.alert_mask,
                     category_t.error_notification | category_t.tracker_notification | category_t.status_notification)
        pack.set_str(string_types.listen_interfaces, settings['listen_interfaces'].encode())
        pack.set_bool(bool_types.enable_dht, settings['enable_dht'])
        pack.set_str(string_types.dht_bootstrap_nodes, settings['dht_bootstrap_nodes'].encode())
        pack.set_int(int_types.alert_queue_size, 4 * MILLION)
        pack.set_int(int_types.cache_size, 4096)
        pack.set_int(int_types.tick_interval, 1000)
        pack.set_int(int_types.connections_limit, 400)
        pack.set_int(int_types.listen_queue_size, 32)
        pack.set_int(int_types.checking_mem_usage, 2048)
        pack.set_int(int_types.aio_threads, 8)
        pack.set_bool(bool_types.listen_system_port_fallback, False)
        pack.set_int(int_types.max_retry_port_bind, 0)
        pack.set_int(int_types.unchoke_slots_limit, 64)

        pack.set_int(int_types.tracker_completion_timeout, 120)
        pack.set_int(int_types.tracker_receive_timeout, 60)
        pack.set_int(int_types.stop_tracker_timeout, 60)

        # Slow torrents
        pack.set_bool(bool_types.dont_count_slow_torrents, True)
        pack.set_int(int_types.auto_manage_startup, 60)
        pack.set_int(int_types.inactive_down_rate, 10 * 1024)
        pack.set_int(int_types.inactive_up_rate, 10 * 1024)

        # Limits
        pack.set_int(int_types.active_downloads, 8)
        pack.set_int(int_types.active_seeds, -1)
        pack.set_int(int_types.active_checking, 32)
        pack.set_int(int_types.active_dht_limit, 1000)
        pack.set_int(int_types.active_tracker_limit, -1)
        pack.set_int(int_types.active_lsd_limit, -1)
        pack.set_int(int_types.active_limit, -1)

        self._session = new session(pack)

    def __dealloc__(self):
        if self._session != NULL:
            printf('Deallocating session\n')
            del self._session

    def async_add_torrent(self, bytes torrent, str download_path, str name, bytes resume_data):
        cdef:
            add_torrent_params add_params
            shared_ptr[torrent_info] lt_torrent_info
            file_storage *files
            int i

        lt_torrent_info = shared_ptr[torrent_info](new torrent_info(torrent, len(torrent)))
        if name is not None:
            files = &(<file_storage&>deref(lt_torrent_info).files())
            files.set_name(name)

        add_params.ti = <shared_ptr[torrent_info]>shared_ptr[torrent_info](lt_torrent_info)
        add_params.save_path = download_path.encode()
        add_params.storage_mode = storage_mode_t.storage_mode_sparse
        add_params.flags = <flags_t>(
                flags_t.flag_pinned | flags_t.flag_update_subscribe | flags_t.flag_auto_managed |
                flags_t.flag_apply_ip_filter | flags_t.flag_duplicate_is_error)

        if resume_data:
            add_params.resume_data = vector[char](len(resume_data))
            for i in range(len(resume_data)):
                add_params.resume_data[i] = resume_data[i]

        self._session.async_add_torrent(add_params)
        # add_params = {
        #     'flags': libtorrent.add_torrent_params_flags_t.default_flags |
        #              libtorrent.add_torrent_params_flags_t.flag_update_subscribe,
        # }
        # if resume_data:
        #     add_params['resume_data'] = resume_data
        #
        # return add_params
