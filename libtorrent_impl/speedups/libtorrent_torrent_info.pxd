from libcpp.string cimport string

cdef extern from 'libtorrent/file_storage.hpp' namespace 'libtorrent':
    cdef cppclass file_storage:
        void set_name(string n)

cdef extern from 'libtorrent/torrent_info.hpp' namespace 'libtorrent':
    cdef cppclass torrent_info:
        string name

        torrent_info(const char *buffer, int size) nogil except +
        const file_storage files()
