#ifndef SESSIONWRAPPER_HPP_
#define SESSIONWRAPPER_HPP_

#include <string>

#include <sqlite3.h>
#include <libtorrent/session.hpp>
#include <libtorrent/settings_pack.hpp>

class SessionWrapper {
    private:

    int config_id;
    libtorrent::session *session;
    sqlite3 *db;

    public:

    SessionWrapper(std::string db_path, int config_id, std::string listen_interfaces, bool enable_dht);
    ~SessionWrapper();
};

#endif
