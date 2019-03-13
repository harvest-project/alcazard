from libcpp.string cimport string
from libcpp.vector cimport vector
from libcpp cimport bool

from .helpers cimport shared_ptr
from .libtorrent_torrent_info cimport torrent_info

cdef extern from 'libtorrent/add_torrent_params.hpp' namespace 'libtorrent':
    cdef enum storage_mode_t:
        storage_mode_allocate
        storage_mode_sparse

    cdef struct add_torrent_params:
        shared_ptr[torrent_info] ti
        string save_path
        storage_mode_t storage_mode
        bool auto_managed
        flags_t flags
        vector[char] resume_data

cdef extern from 'libtorrent/add_torrent_params.hpp' namespace 'libtorrent::add_torrent_params':
    cdef enum flags_t:
        flag_pinned
        flag_update_subscribe
        flag_auto_managed
        flag_apply_ip_filter
        flag_duplicate_is_error
