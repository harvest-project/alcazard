#ifndef SESSIONWRAPPER_HPP_
#define SESSIONWRAPPER_HPP_

#include <string>
#include <unordered_map>

#include <sqlite3.h>
#include <libtorrent/alert_types.hpp>
#include <libtorrent/session.hpp>
#include <libtorrent/settings_pack.hpp>
#include <libtorrent/add_torrent_params.hpp>
#include <libtorrent/session_status.hpp>

#include "TorrentState.hpp"

namespace lt = libtorrent;

class SessionWrapper {
private:

    int config_id;
    libtorrent::session *session;
    sqlite3 *db;

    void init_add_params(lt::add_torrent_params &params, std::string torrent, std::string download_path,
                         std::string *name, std::string *resume_data);

    TorrentState *handle_torrent_added(lt::torrent_status *status, std::string *torrent_file = NULL);

    void on_alert_add_torrent(BatchTorrentUpdate *update, lt::add_torrent_alert *alert);

    void on_alert_state_update(BatchTorrentUpdate *update, lt::state_update_alert *alert);

public:

    std::unordered_map<std::string, TorrentState *> torrent_states;

    SessionWrapper(
            std::string db_path,
            int config_id,
            std::string listen_interfaces,
            bool enable_dht
    );

    ~SessionWrapper();

    void load_initial_torrents();

    void async_add_torrent(
            std::string torrent,
            std::string download_path,
            std::string *name,
            std::string *resume_data
    );

    void post_torrent_updates();

    void pause();

    int listen_port();

    BatchTorrentUpdate process_alerts();

    lt::session_status status();
};

#endif
