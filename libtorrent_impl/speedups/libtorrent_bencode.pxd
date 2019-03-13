cdef extern from 'libtorrent/entry.hpp' namespace 'libtorrent':
    cdef cppclass entry

cdef extern from 'libtorrent/bencode.hpp' namespace 'libtorrent':
    cdef entry bdecode() nogil
