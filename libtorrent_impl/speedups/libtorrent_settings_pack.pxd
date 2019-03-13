from libcpp cimport bool
from libcpp.string cimport string

cdef extern from 'libtorrent/settings_pack.hpp' namespace 'libtorrent::settings_pack':
    enum string_types:
        user_agent
        peer_fingerprint
        listen_interfaces
        dht_bootstrap_nodes

    enum bool_types:
        enable_dht
        listen_system_port_fallback
        dont_count_slow_torrents

    enum int_types:
        alert_mask
        alert_queue_size
        cache_size
        tick_interval
        connections_limit
        listen_queue_size
        checking_mem_usage
        aio_threads
        max_retry_port_bind
        unchoke_slots_limit
        tracker_completion_timeout
        tracker_receive_timeout
        stop_tracker_timeout
        auto_manage_startup
        inactive_down_rate
        inactive_up_rate
        active_downloads
        active_seeds
        active_checking
        active_dht_limit
        active_tracker_limit
        active_lsd_limit
        active_limit

cdef extern from 'libtorrent/settings_pack.hpp' namespace 'libtorrent':
    cdef cppclass settings_pack:
        void set_str(int name, string val) nogil
        void set_int(int name, int val) nogil
        void set_bool(int name, bool val) nogil
        bool has_val(int name) nogil

        void clear() nogil
        void clear(int name) nogil

        string get_str(int name) nogil
        int get_int(int name) nogil
        bool get_bool(int name) nogil
