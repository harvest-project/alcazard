cdef extern from 'libtorrent/alert.hpp' namespace 'libtorrent::alert':
    enum category_t:
        error_notification
        tracker_notification
        status_notification
