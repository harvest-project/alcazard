from libc.stdint cimport int64_t
from libcpp.string cimport string

cdef extern from 'libtorrent/hex.hpp' namespace 'libtorrent':
    cdef string to_hex(const string& s) nogil except +

cdef extern from 'libtorrent/alert.hpp' namespace 'libtorrent':
    cdef cppclass alert:
        pass

cdef extern from 'libtorrent/sha1_hash.hpp' namespace 'libtorrent':
    cdef cppclass sha1_hash:
        char* data() nogil except +
        string to_string() nogil except +

cdef extern from 'libtorrent/torrent_status.hpp' namespace 'libtorrent':
    cdef struct torrent_status:
        sha1_hash info_hash

cdef extern from 'libtorrent/torrent_handle.hpp' namespace 'libtorrent':
    cdef struct torrent_handle:
        torrent_status status() nogil except +

cdef extern from 'libtorrent/alert_types.hpp' namespace 'libtorrent':
    cdef struct torrent_added_alert:
        torrent_handle handle

cdef extern from 'libtorrent/session_status.hpp' namespace 'libtorrent':
    cdef struct session_status:
        int64_t total_payload_download
        int64_t total_payload_upload
        int payload_download_rate
        int payload_upload_rate
