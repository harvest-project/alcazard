#include <string>
#include <algorithm>
#include <sqlite3.h>
#include <libtorrent/torrent_info.hpp>
#include <libtorrent/hex.hpp>
#include <libtorrent/error_code.hpp>
#include <libtorrent/session_stats.hpp>

#include "SqliteHelper.hpp"
#include "Utils.hpp"
#include "SessionWrapper.hpp"

namespace lt = libtorrent;

Logger logger("SessionWrapper");

SessionWrapper::SessionWrapper(
        std::string db_path,
        int config_id,
        std::string listen_interfaces,
        bool enable_dht)
        : config_id(config_id), session(NULL), db(NULL) {
    logger.debug("Opening SQLite DB.");
    SQLITE_CHECK(sqlite3_open_v2(db_path.c_str(), &this->db, SQLITE_OPEN_READWRITE, NULL));

    lt::settings_pack pack = this->create_settings_pack();
    pack.set_str(lt::settings_pack::listen_interfaces, listen_interfaces);
    pack.set_bool(lt::settings_pack::enable_dht, enable_dht);

    this->init_metrics_names();

    logger.info("Creating libtorrent session.");
    this->session = new libtorrent::session(pack);
}

lt::settings_pack SessionWrapper::create_settings_pack() {
    lt::settings_pack pack;
    const int alert_mask =
            lt::alert::error_notification
            | lt::alert::tracker_notification
            | lt::alert::status_notification;
    // Basic settings
    pack.set_int(lt::settings_pack::alert_mask, alert_mask);
    pack.set_str(lt::settings_pack::user_agent, "Deluge/1.2.15");
    pack.set_str(lt::settings_pack::peer_fingerprint, "-DE13F0-");
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
    return pack;
}

void SessionWrapper::init_metrics_names() {
    char name[128];
    for (auto &metric : lt::session_stats_metrics()) {
        snprintf(
                name,
                sizeof(name) / sizeof(name[0]),
                "%s[%s]",
                metric.name,
                metric.type == lt::stats_metric::type_counter ? "counter" : "gauge"
        );
        this->metrics_names.push_back(std::make_pair(name, metric.value_index));
    }
}

SessionWrapper::~SessionWrapper() {
    if (this->session) {
        delete this->session;
    }
    if (this->db) {
        // Discard error, since this is a destructor
        sqlite3_close_v2(this->db);
    }
}

void SessionWrapper::load_initial_torrents() {
    auto timer = timers.start_timer("load_initial_torrents");
    logger.info("Loading initial torrents.");
    this->timer_initial_torrents_received = timers.start_timer("initial_torrents_received");

    SqliteStatement fetch_stmt = SqliteStatement(
            this->db,
            "SELECT id, torrent_file, download_path, name, resume_data FROM libtorrenttorrent WHERE libtorrent_id = ?001"
    );
    fetch_stmt.bind_int64(1, this->config_id);

    int i = 0;
    while (fetch_stmt.step()) {
        if (i++ >= 10000000) break;

        logger.debug("Async adding torrent %lld.", fetch_stmt.get_int64(0));
        this->num_waiting_initial_torrents++;
        bool has_name = !fetch_stmt.get_is_null(3);
        std::string name = has_name ? fetch_stmt.get_text(3) : "";
        bool has_resume_data = !fetch_stmt.get_is_null(4);
        std::string resume_data = has_resume_data ? fetch_stmt.get_blob(4) : "";

        lt::add_torrent_params add_params;
        this->init_add_params(
                add_params,
                fetch_stmt.get_blob(1),
                fetch_stmt.get_blob(2),
                has_name ? &name : NULL,
                has_resume_data ? &resume_data : NULL
        );
        this->session->async_add_torrent(add_params);
    }

    logger.info("Completed initial torrent load.");
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
    auto timer = timers.start_timer("post_torrent_updates");
    this->session->post_torrent_updates(0);
}

void SessionWrapper::pause() {
    auto timer = timers.start_timer("pause");
    logger.info("Pausing session.");
    this->session->pause();
}

BatchTorrentUpdate SessionWrapper::process_alerts() {
    auto timer = timers.start_timer("process_alerts");
    BatchTorrentUpdate update;
    std::vector < lt::alert * > alerts;
    this->session->pop_alerts(&alerts);

    for (auto alert : alerts) {
        if (auto a = lt::alert_cast<lt::add_torrent_alert>(alert)) {
            this->on_alert_add_torrent(&update, a);
        } else if (auto a = lt::alert_cast<lt::state_update_alert>(alert)) {
            this->on_alert_state_update(&update, a);
        } else if (auto a = lt::alert_cast<lt::session_stats_alert>(alert)) {
            this->on_alert_session_stats(&update, a);
        }
    }

    if (update.added_handles.size()) {
//        std::vector <lt::torrent_status> added_statuses;
//        for (auto added_handle : update.added_handles) {
//            lt::torrent_status status;
//            status.handle = added_handle;
//            added_statuses.push_back(status);
//        }
//        {
//            auto timer = timers.start_timer("refresh_new_statuses");
//            this->session->refresh_torrent_status(&added_statuses, 0);
//        }
//        for (auto &status : added_statuses) {
//            TorrentState *state = this->handle_torrent_added(&status);
//            update.added.push_back(state);
//            --this->num_waiting_initial_torrents;
//        }
    }

    if (this->timer_initial_torrents_received && this->num_waiting_initial_torrents <= 0) {
        logger.info("Received all initial torrents.");
        this->timer_initial_torrents_received.reset();
    }

    return update;
}

TorrentState *SessionWrapper::handle_torrent_added(lt::torrent_status *status, std::string *torrent_file) {
    std::string info_hash = status->info_hash.to_string();
    if (this->torrent_states.find(info_hash) != this->torrent_states.end()) {
        throw std::runtime_error("Torrent already added");
    }
    TorrentState *state = new TorrentState(status);
    this->torrent_states[info_hash] = state;
    return state;
}

void SessionWrapper::post_session_stats() {
    auto timer = timers.start_timer("post_session_stats");
    return this->session->post_session_stats();
}

TimerStats SessionWrapper::get_timer_stats() {
    return this->timers.stats;
}

void SessionWrapper::on_alert_add_torrent(BatchTorrentUpdate *update, lt::add_torrent_alert *alert) {
    if (alert->error) {
        // TODO: Describe the actual error
        logger.error("Error adding torrent!");
        throw std::runtime_error("Libtorrent returned error adding torrent.");
    }
    update->added_handles.push_back(alert->handle);
}

void SessionWrapper::on_alert_state_update(BatchTorrentUpdate *update, lt::state_update_alert *alert) {
    logger.debug("Received state updates for %lu torrents.", alert->status.size());
    for (auto &status : alert->status) {
        std::string info_hash = status.info_hash.to_string();
        auto state = this->torrent_states.find(info_hash);
        if (state == this->torrent_states.end()) {
            TorrentState *state = this->handle_torrent_added(&status);
            update->added.push_back(state);
            --this->num_waiting_initial_torrents;
        } else if (state->second->update_from_status(&status)) {
            update->updated.push_back(state->second);
        }
    }
}

void SessionWrapper::on_alert_session_stats(BatchTorrentUpdate *update, lt::session_stats_alert *alert) {
    logger.debug("Received session stats.");
    for (auto &item : this->metrics_names) {
        update->metrics[item.first] = alert->values[item.second];
    }
    // Piggyback a session stats update to post timers as well
    update->timer_stats = this->timers.stats;
}
