from libcpp cimport bool

cdef extern from 'boost/shared_ptr.hpp' namespace 'boost':
    cdef cppclass shared_ptr[T]:
        shared_ptr()
        shared_ptr(T*)
        shared_ptr(shared_ptr[T]&)
        T* get()
        T& operator*()
        void reset(T*)
        bool operator bool()
