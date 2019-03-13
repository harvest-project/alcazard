from .libtorrent_settings_pack cimport settings_pack
from .libtorrent_add_torrent_params cimport add_torrent_params

cdef extern from 'libtorrent/session.hpp' namespace 'libtorrent':
    cdef cppclass session:
        session(settings_pack settings) nogil except +

        void async_add_torrent(const add_torrent_params& params)
