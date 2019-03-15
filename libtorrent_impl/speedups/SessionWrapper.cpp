#include <string>

#include <sqlite3.h>
#include <libtorrent/torrent_info.hpp>
#include <libtorrent/hex.hpp>
#include <libtorrent/error_code.hpp>

#include "SqliteHelper.hpp"
#include "SessionWrapper.hpp"

namespace lt = libtorrent;

SessionWrapper::SessionWrapper(
        std::string db_path,
        int config_id,
        std::string listen_interfaces,
        bool enable_dht)
        : config_id(config_id), session(NULL), db(NULL) {
    printf("Open sqlite3\n");
    SQLITE_CHECK(sqlite3_open_v2(db_path.c_str(), &this->db, SQLITE_OPEN_READWRITE, NULL));

    const int alert_mask =
            lt::alert::error_notification
            | lt::alert::tracker_notification
            | lt::alert::status_notification;

    printf("New session %d\n", this->config_id);
    lt::settings_pack pack;
    pack.set_str(lt::settings_pack::user_agent, "Deluge/1.2.15");
    pack.set_str(lt::settings_pack::peer_fingerprint, "-DE13F0-");
    pack.set_int(lt::settings_pack::alert_mask, alert_mask);
    pack.set_str(lt::settings_pack::listen_interfaces, listen_interfaces);
    pack.set_bool(lt::settings_pack::enable_dht, enable_dht);
    pack.set_str(lt::settings_pack::dht_bootstrap_nodes,
                 "router.bittorrent.com:6881,router.utorrent.com:6881,router.bitcomet.com:6881,dht.transmissionbt.com:6881,"
                 "dht.aelitis.com:6881");
    pack.set_int(lt::settings_pack::alert_queue_size, 4 * 1000 * 1000);
    pack.set_int(lt::settings_pack::cache_size, 4096);
    pack.set_int(lt::settings_pack::tick_interval, 1000);
    pack.set_int(lt::settings_pack::connections_limit, 400);
    pack.set_int(lt::settings_pack::listen_queue_size, 32);
    pack.set_int(lt::settings_pack::checking_mem_usage, 2048);
    pack.set_int(lt::settings_pack::aio_threads, 8);
    pack.set_bool(lt::settings_pack::listen_system_port_fallback, false);
    pack.set_int(lt::settings_pack::max_retry_port_bind, 0);
    pack.set_int(lt::settings_pack::unchoke_slots_limit, 64);

    pack.set_int(lt::settings_pack::tracker_completion_timeout, 120);
    pack.set_int(lt::settings_pack::tracker_receive_timeout, 60);
    pack.set_int(lt::settings_pack::stop_tracker_timeout, 60);

    // Slow torrents
    pack.set_bool(lt::settings_pack::dont_count_slow_torrents, true);
    pack.set_int(lt::settings_pack::auto_manage_startup, 60);
    pack.set_int(lt::settings_pack::inactive_down_rate, 10 * 1024);
    pack.set_int(lt::settings_pack::inactive_up_rate, 10 * 1024);

    // Limits
    pack.set_int(lt::settings_pack::active_downloads, 8);
    pack.set_int(lt::settings_pack::active_seeds, -1);
    pack.set_int(lt::settings_pack::active_checking, 32);
    pack.set_int(lt::settings_pack::active_dht_limit, 1000);
    pack.set_int(lt::settings_pack::active_tracker_limit, -1);
    pack.set_int(lt::settings_pack::active_lsd_limit, -1);
    pack.set_int(lt::settings_pack::active_limit, -1);

    this->session = new libtorrent::session(pack);
}

SessionWrapper::~SessionWrapper() {
    if (this->session) {
        printf("Delete session\n");
        delete this->session;
    }
    if (this->db) {
        printf("Delete db");
        // Discard error, since this is a destructor
        sqlite3_close_v2(this->db);
    }
}

void SessionWrapper::load_initial_torrents() {
    std::vector <int64_t> ids;
    SqliteStatement list_stmt(this->db, "SELECT id FROM libtorrenttorrent WHERE libtorrent_id = ?001");
    list_stmt.bind_int64(1, this->config_id);
    while (list_stmt.step()) {
        ids.push_back(sqlite3_column_int64(list_stmt.ptr, 0));
    }

    printf("C++ received a total of %lu torrents\n", ids.size());

    SqliteStatement fetch_stmt = SqliteStatement(
            this->db,
            "SELECT torrent_file, download_path, name, resume_data FROM libtorrenttorrent WHERE id = ?001"
    );
    for (auto id : ids) {
        fetch_stmt.clear_bindings();
        fetch_stmt.bind_int64(1, id);
        while (fetch_stmt.step()) {
            bool has_name = !fetch_stmt.get_is_null(2);
            std::string name = has_name ? fetch_stmt.get_text(2) : "";
            bool has_resume_data = !fetch_stmt.get_is_null(3);
            std::string resume_data = has_resume_data ? fetch_stmt.get_blob(3) : "";
            this->async_add_torrent(
                    fetch_stmt.get_blob(0),
                    fetch_stmt.get_blob(1),
                    has_name ? &name : NULL,
                    has_resume_data ? &resume_data : NULL
            );
        }
        fetch_stmt.reset();
    }

    printf("C++ completed initial torrent load\n");
}

void SessionWrapper::init_add_params(lt::add_torrent_params &params, std::string torrent, std::string download_path,
                                     std::string *name, std::string *resume_data) {
    params.flags = lt::add_torrent_params::flag_pinned |
                   lt::add_torrent_params::flag_update_subscribe |
                   lt::add_torrent_params::flag_auto_managed |
                   lt::add_torrent_params::flag_apply_ip_filter |
                   lt::add_torrent_params::flag_duplicate_is_error;
    params.ti = boost::shared_ptr<lt::torrent_info>(
            new lt::torrent_info(torrent.c_str(), torrent.size()));
    params.save_path = download_path;
    if (resume_data != NULL) {
        params.resume_data = std::vector<char>(resume_data->begin(), resume_data->end());
    }
    if (name != NULL) {
        ((libtorrent::file_storage) params.ti->files()).set_name(*resume_data);
    }
}

void SessionWrapper::async_add_torrent(
        std::string torrent,
        std::string download_path,
        std::string *name,
        std::string *resume_data) {
    lt::add_torrent_params add_params;
    this->init_add_params(add_params, torrent, download_path, name, resume_data);
    this->session->async_add_torrent(add_params);
}

void SessionWrapper::post_torrent_updates() {
    this->session->post_torrent_updates(0);
}

void SessionWrapper::pause() {
    this->session->pause();
}

int SessionWrapper::listen_port() {
    return this->session->listen_port();
}

BatchTorrentUpdate SessionWrapper::process_alerts() {
    BatchTorrentUpdate update;
    std::vector < lt::alert * > alerts;
    this->session->pop_alerts(&alerts);

    for (auto alert : alerts) {
        if (auto a = lt::alert_cast<lt::add_torrent_alert>(alert)) {
            this->on_alert_add_torrent(&update, a);
        } else if (auto a = lt::alert_cast<lt::state_update_alert>(alert)) {
            this->on_alert_state_update(&update, a);
        }
    }

    if (update.added_handles.size()) {
        std::vector <lt::torrent_status> added_statuses;
        for (auto added_handle : update.added_handles) {
            lt::torrent_status status;
            status.handle = added_handle;
            added_statuses.push_back(status);
        }
        this->session->refresh_torrent_status(&added_statuses, 0);
        for (auto status : added_statuses) {
            TorrentState *state = this->handle_torrent_added(&status);
            update.added.push_back(state);
        }
    }

    return update;
}

TorrentState *SessionWrapper::handle_torrent_added(lt::torrent_status *status, std::string *torrent_file) {
    std::string info_hash = status->info_hash.to_string();
//    printf("C++ torrent added %s\n", lt::to_hex(info_hash).c_str());
    if (this->torrent_states.find(info_hash) != this->torrent_states.end()) {
        throw std::runtime_error("Torrent already added");
    }
    TorrentState *state = new TorrentState(status);
    this->torrent_states[info_hash] = state;
    return state;
}

lt::session_status SessionWrapper::status() {
    return this->session->status();
}

void SessionWrapper::on_alert_add_torrent(BatchTorrentUpdate *update, lt::add_torrent_alert *alert) {
    if (alert->error) {
        // TODO: Describe the actual error
        printf("LIBTORRENT ALERT ERROR %d\n", alert->error.value());
        throw std::runtime_error("Libtorrent returned error adding torrent");
    }
    update->added_handles.push_back(alert->handle);
}

void SessionWrapper::on_alert_state_update(BatchTorrentUpdate *update, lt::state_update_alert *alert) {
    printf("C++ Received state updates for %lu torrents.\n", alert->status.size());
    for (auto status : alert->status) {
        std::string info_hash = status.info_hash.to_string();
//        printf("C++ received state update for %s\n", lt::to_hex(info_hash).c_str());
        auto state = this->torrent_states.find(info_hash);
        if (state == this->torrent_states.end()) {
            throw new std::runtime_error("Received update for unregistered torrent");
        }
        if (state->second->update_from_status(&status)) {
            update->updated.push_back(state->second);
        }
    }
}
