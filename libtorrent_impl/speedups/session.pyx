# cython: language_level=3

from libcpp cimport bool as cbool
from cpython cimport bool as pybool
from libcpp.string cimport string

DEF MILLION = 10 ** 6

cdef extern from "SessionWrapper.hpp":
    cdef cppclass SessionWrapper:
        SessionWrapper(string db_path, int config_id, string listen_interfaces, cbool enable_dht) nogil except +

cdef class LibtorrentSession:
    cdef SessionWrapper *wrapper

    def __init__(self, str db_path, int config_id, str listen_interfaces, pybool enable_dht):
        self.wrapper = new SessionWrapper(
            db_path.encode(),
            config_id,
            listen_interfaces.encode(),
            enable_dht,
        )

    def __dealloc__(self):
        del self.wrapper
