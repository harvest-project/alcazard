#include <string>
#include <algorithm>
#include <sqlite3.h>
#include <libtorrent/torrent_info.hpp>
#include <libtorrent/hex.hpp>
#include <libtorrent/error_code.hpp>
#include <libtorrent/session_stats.hpp>
#include <libtorrent/bencode.hpp>
#include <libtorrent/storage_defs.hpp>

#include "SqliteHelper.hpp"
#include "Utils.hpp"
#include "SessionWrapper.hpp"
#include "yuarel.hpp"

namespace lt = libtorrent;

Logger logger("SessionWrapper");

SessionWrapper::SessionWrapper(
        std::string db_path,
        std::string listen_interfaces,
        bool enable_dht,
        bool enable_file_preallocation)
        : session(NULL), db(NULL),
          enable_file_preallocation(enable_file_preallocation),
          num_initial_torrents(-1),
          num_loaded_initial_torrents(-2) {
    logger.debug("Opening SQLite DB.");
    SQLITE_CHECK(sqlite3_open_v2(db_path.c_str(), &this->db, SQLITE_OPEN_READWRITE, NULL));

    lt::settings_pack pack;
    this->init_settings_pack(&pack);
    pack.set_str(lt::settings_pack::listen_interfaces, listen_interfaces);
    pack.set_bool(lt::settings_pack::enable_dht, enable_dht);

    this->init_metrics_names();
    this->read_session_stats();

    logger.info("Creating libtorrent session.");
    this->session = new libtorrent::session(pack);
}

void SessionWrapper::init_settings_pack(lt::settings_pack *pack) {
    const int alert_mask =
            lt::alert::error_notification
            | lt::alert::tracker_notification
            | lt::alert::status_notification;
    // Basic settings
    pack->set_int(lt::settings_pack::alert_mask, alert_mask);
    pack->set_str(lt::settings_pack::user_agent, "Deluge/1.2.15");
    pack->set_str(lt::settings_pack::peer_fingerprint, "-DE13F0-");
    pack->set_str(lt::settings_pack::dht_bootstrap_nodes,
                  "router.bittorrent.com:6881,router.utorrent.com:6881,router.bitcomet.com:6881,dht.transmissionbt.com:6881,"
                  "dht.aelitis.com:6881");
    pack->set_int(lt::settings_pack::alert_queue_size, 4 * 1000 * 1000);
    pack->set_int(lt::settings_pack::tick_interval, 1000);
    pack->set_int(lt::settings_pack::aio_threads, 8);
    pack->set_bool(lt::settings_pack::listen_system_port_fallback, false);
    pack->set_int(lt::settings_pack::max_retry_port_bind, 0);
    pack->set_int(lt::settings_pack::unchoke_slots_limit, 64);
    // Disable read caching to try avoid seeming memory leaks and save memory
    pack->set_bool(lt::settings_pack::use_read_cache, false);
    // Reduce peer list size to save memory, down from 4000
    pack->set_bool(lt::settings_pack::max_peerlist_size, 256);
    // Reduce send buffers to conserve memory, down from 500 * 1024
    pack->set_int(lt::settings_pack::send_buffer_watermark, 200 * 1024);

    pack->set_int(lt::settings_pack::tracker_completion_timeout, 120);
    pack->set_int(lt::settings_pack::tracker_receive_timeout, 60);
    pack->set_int(lt::settings_pack::stop_tracker_timeout, 0);

    // Slow torrents
    pack->set_bool(lt::settings_pack::dont_count_slow_torrents, true);
    pack->set_int(lt::settings_pack::auto_manage_startup, 60);
    pack->set_int(lt::settings_pack::inactive_down_rate, 10 * 1024);
    pack->set_int(lt::settings_pack::inactive_up_rate, 10 * 1024);

    // Limits
    pack->set_int(lt::settings_pack::active_downloads, 8);
    pack->set_int(lt::settings_pack::active_seeds, -1);
    pack->set_int(lt::settings_pack::active_checking, 32);
    pack->set_int(lt::settings_pack::active_dht_limit, 1000);
    pack->set_int(lt::settings_pack::active_tracker_limit, -1);
    pack->set_int(lt::settings_pack::active_lsd_limit, -1);
    pack->set_int(lt::settings_pack::active_limit, -1);
}

void SessionWrapper::read_session_stats() {
    logger.debug("Reading session stats");
    SqliteStatement stmt = SqliteStatement(this->db, "SELECT total_downloaded, total_uploaded FROM sessionstats");
    if (!stmt.step()) {
        throw std::runtime_error("Unable to read session stats.");
    }
    this->start_total_downloaded = stmt.get_int64(0);
    this->start_total_uploaded = stmt.get_int64(1);
    logger.debug("Read session stats");
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

int SessionWrapper::load_initial_torrents() {
    auto timer = timers.start_timer("load_initial_torrents");
    logger.info("Loading initial torrents.");

    if (this->num_initial_torrents == -1) {
        this->timer_initial_torrents_received = timers.start_timer("initial_torrents_received");
        SqliteStatement count_stmt = SqliteStatement(this->db, "SELECT COUNT(*) FROM torrent");
        count_stmt.step();
        this->num_loaded_initial_torrents = 0;
        this->num_initial_torrents = (int) count_stmt.get_int64(0);
    }

    SqliteStatement fetch_stmt = SqliteStatement(
            this->db, "SELECT id, torrent_file, download_path, name, resume_data FROM torrent");

    int loaded = 0;
    while (fetch_stmt.step()) {
        int64_t row_id = fetch_stmt.get_int64(0);

        if (this->loaded_torrent_ids.find(row_id) != this->loaded_torrent_ids.end()) {
            continue;
        }
        if (++loaded > 5000) return this->loaded_torrent_ids.size();
        this->loaded_torrent_ids.insert(row_id);

        logger.debug("Async adding torrent %lld.", row_id);
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
        add_params.userdata = (void *) row_id;
        this->session->async_add_torrent(add_params);
    }

    logger.info("Completed initial torrent load.");
    return this->loaded_torrent_ids.size();
}

void SessionWrapper::init_add_params(lt::add_torrent_params &params, std::string torrent, std::string download_path,
                                     std::string *name, std::string *resume_data) {
    params.flags = lt::add_torrent_params::flag_pinned |
                   lt::add_torrent_params::flag_update_subscribe |
                   lt::add_torrent_params::flag_apply_ip_filter |
                   lt::add_torrent_params::flag_duplicate_is_error;
    params.ti = boost::shared_ptr<lt::torrent_info>(
            new lt::torrent_info(torrent.c_str(), torrent.size()));
    params.save_path = download_path;
    params.storage_mode = this->enable_file_preallocation ? lt::storage_mode_allocate : lt::storage_mode_sparse;
    if (resume_data != NULL) {
        params.resume_data = std::vector<char>(resume_data->begin(), resume_data->end());
    }
    if (name != NULL) {
        ((libtorrent::file_storage) params.ti->files()).set_name(*resume_data);
    }
}

std::shared_ptr <TorrentState> SessionWrapper::add_torrent(
        std::string torrent_file,
        std::string download_path,
        std::string *name) {
    lt::add_torrent_params add_params;
    this->init_add_params(add_params, torrent_file, download_path, name, NULL);
    lt::torrent_handle handle = this->session->add_torrent(add_params);
    lt::torrent_status status = handle.status();
    std::string info_hash = status.info_hash.to_string();
    std::shared_ptr <TorrentState> state = std::make_shared<TorrentState>(-1, &status);
    this->apply_pre_load_tracker_state(state);
    state->insert_db_row(this->db, torrent_file, download_path, name);
    this->torrent_states[info_hash] = state;
    return state;
}

void SessionWrapper::remove_torrent(std::string info_hash_str) {
    logger.debug("Called remove for %s.", info_hash_str.c_str());
    if (info_hash_str.size() != lt::sha1_hash::size * 2) {
        throw std::runtime_error("Bad info_hash parameter.");
    }
    char buf[lt::sha1_hash::size];
    if (!lt::from_hex(info_hash_str.c_str(), info_hash_str.size(), buf)) {
        throw std::runtime_error("Error decoding hex str");
    }
    auto state_item = this->torrent_states.find(std::string(buf, lt::sha1_hash::size));
    if (state_item == this->torrent_states.end()) {
        throw std::runtime_error("Torrent not found.");
    }
    this->session->remove_torrent(state_item->second->handle, lt::session::delete_files);
}

void SessionWrapper::post_torrent_updates() {
    auto timer = timers.start_timer("post_torrent_updates");
    this->session->post_torrent_updates(
            lt::torrent_handle::query_name | lt::torrent_handle::query_save_path);
}

void SessionWrapper::pause() {
    auto timer = timers.start_timer("pause");
    logger.info("Pausing session.");
    this->session->pause();
}

BatchTorrentUpdate SessionWrapper::process_alerts(bool shutting_down) {
    auto timer = timers.start_timer("process_alerts");
    BatchTorrentUpdate update;
    std::vector < lt::alert * > alerts;
    this->session->pop_alerts(&alerts);

    if (!shutting_down) {
        for (auto alert : alerts) {
            this->dispatch_alert(&update, alert);
        }
    } else {
        for (auto alert : alerts) {
            this->dispatch_alert_shutting_down(&update, alert);
        }
    }

    // Those write to the DB, so execute them 10K at a time inside transactions.
    if (update.save_resume_data_alerts.size()) {
        auto transaction = SqliteTransaction(this->db);
        int num_alerts = 0;
        for (auto alert : update.save_resume_data_alerts) {
            this->on_alert_save_resume_data(&update, alert);
            if (++num_alerts % 10000 == 0) {
                transaction.commit();
            }
        }
    }

    if (this->timer_initial_torrents_received && this->num_loaded_initial_torrents >= this->num_initial_torrents) {
        logger.info("Received all initial torrents.");
        this->timer_initial_torrents_received.reset();
    }

    update.num_waiting_for_resume_data = this->info_hashes_resume_data_wait.size();
    update.succeeded_listening = this->succeeded_listening;

    return update;
}

std::shared_ptr <TorrentState> SessionWrapper::handle_torrent_added(lt::torrent_status *status) {
    auto timer = this->timers.start_timer("handle_torrent_added");
    std::string info_hash = status->info_hash.to_string();
    if (this->torrent_states.find(info_hash) != this->torrent_states.end()) {
        // Torrent already created when calling add_torrent
        return std::shared_ptr<TorrentState>(NULL);
    }

    int64_t row_id;
    auto row_id_item = this->added_torrent_row_ids.find(info_hash);
    if (row_id_item != this->added_torrent_row_ids.end()) {
        row_id = row_id_item->second;
        this->added_torrent_row_ids.erase(row_id_item);
    } else {
        logger.error("Torrent didn't existing in torrent_states and no row_id was provided.");
        return std::shared_ptr<TorrentState>(NULL);
    }

    std::shared_ptr <TorrentState> state = std::make_shared<TorrentState>(row_id, status);
    this->apply_pre_load_tracker_state(state);
    this->torrent_states[info_hash] = state;
    return state;
}

void SessionWrapper::post_session_stats() {
    auto timer = timers.start_timer("post_session_stats");
    return this->session->post_session_stats();
}

void SessionWrapper::all_torrents_save_resume_data(bool flush_cache) {
    auto timer = this->timers.start_timer("all_save_resume_data");
    logger.info("Triggered all_save_resume_data");
    int flags = lt::torrent_handle::only_if_modified;
    if (flush_cache) {
        flags |= lt::torrent_handle::flush_disk_cache;
    }
    for (auto &item : this->torrent_states) {
        std::string info_hash = item.second->info_hash;
        if (logger.is_enabled_for(Logger::DEBUG)) {
            logger.debug("Triggering save resume data for %s.", lt::to_hex(info_hash).c_str());
        }
        this->info_hashes_resume_data_wait.insert(info_hash);
        item.second->handle.save_resume_data(flags);
    }
}

void SessionWrapper::on_alert_add_torrent(BatchTorrentUpdate *update, lt::add_torrent_alert *alert) {
    if (alert->error) {
        // TODO: Describe the actual error
        logger.error("Libtorrent returned error adding torrent!");
        return;
    }
    this->added_torrent_row_ids[alert->handle.info_hash().to_string()] = (int64_t) alert->params.userdata;
}

void SessionWrapper::on_alert_state_update(BatchTorrentUpdate *update, lt::state_update_alert *alert) {
    logger.debug("Received state updates for %lu torrents.", alert->status.size());
    for (auto &status : alert->status) {
        std::string info_hash = status.info_hash.to_string();
        auto state = this->torrent_states.find(info_hash);
        if (state == this->torrent_states.end()) {
            std::shared_ptr <TorrentState> state = this->handle_torrent_added(&status);
            if (!state) {
                logger.error("handle_torrent_added returned NULL pointer.");
                continue;
            }
            update->added.push_back(state);
            ++this->num_loaded_initial_torrents;
        } else if (state->second->update_from_status(&status)) {
            update->updated.push_back(state->second);
        }
    }
}

void SessionWrapper::apply_pre_load_tracker_state(std::shared_ptr <TorrentState> state) {
    auto tracker_state = this->pre_load_tracker_states.find(state->info_hash);
    if (tracker_state != this->pre_load_tracker_states.end()) {
        if (logger.is_enabled_for(Logger::DEBUG)) {
            logger.debug("Found pre_load_tracker state for %s.", lt::to_hex(state->info_hash).c_str());
        }
        state->tracker_status = tracker_state->second.tracker_status;
        state->tracker_error = tracker_state->second.tracker_error;
        this->pre_load_tracker_states.erase(tracker_state);
    }
}

void SessionWrapper::calculate_torrent_count_metrics(BatchTorrentUpdate *update) {
    auto timer = this->timers.start_timer("calculate_torrent_count_metrics");
    int tracker_statuses[TRACKER_STATUS_MAX];
    memset(tracker_statuses, 0, sizeof(tracker_statuses));
    int states[lt::torrent_status::checking_resume_data + 1];
    memset(states, 0, sizeof(states));
    for (auto &item : this->torrent_states) {
        tracker_statuses[item.second->tracker_status]++;
        states[item.second->state]++;
    }

    update->metrics["alcazar.torrents.count[gauge]"] = this->torrent_states.size();
    update->metrics["alcazar.torrents.num_initial[gauge]"] = this->num_initial_torrents;
    update->metrics["alcazar.torrents.num_loaded_initial[gauge]"] = this->num_loaded_initial_torrents;
    update->metrics["alcazar.torrents.tracker_status.pending[gauge]"] = tracker_statuses[TRACKER_STATUS_PENDING];
    update->metrics["alcazar.torrents.tracker_status.announcing[gauge]"] = tracker_statuses[TRACKER_STATUS_ANNOUNCING];
    update->metrics["alcazar.torrents.tracker_status.error[gauge]"] = tracker_statuses[TRACKER_STATUS_ERROR];
    update->metrics["alcazar.torrents.tracker_status.success[gauge]"] = tracker_statuses[TRACKER_STATUS_SUCCESS];

    update->metrics["alcazar.torrents.state.queued_for_checking[gauge]"] = states[
            lt::torrent_status::queued_for_checking];
    update->metrics["alcazar.torrents.state.checking_files[gauge]"] = states[lt::torrent_status::checking_files];
    update->metrics["alcazar.torrents.state.downloading_metadata[gauge]"] = states[
            lt::torrent_status::downloading_metadata];
    update->metrics["alcazar.torrents.state.downloading[gauge]"] = states[lt::torrent_status::downloading];
    update->metrics["alcazar.torrents.state.finished[gauge]"] = states[lt::torrent_status::finished];
    update->metrics["alcazar.torrents.state.seeding[gauge]"] = states[lt::torrent_status::seeding];
    update->metrics["alcazar.torrents.state.allocating[gauge]"] = states[lt::torrent_status::allocating];
    update->metrics["alcazar.torrents.state.checking_resume_data[gauge]"] = states[
            lt::torrent_status::checking_resume_data];
}

void SessionWrapper::update_session_stats(BatchTorrentUpdate *update) {
    int64_t total_downloaded = this->start_total_downloaded + update->metrics["net.recv_payload_bytes[counter]"];
    int64_t total_uploaded = this->start_total_uploaded + update->metrics["net.sent_payload_bytes[counter]"];
    update->metrics["alcazar.session.total_downloaded[counter]"] = total_downloaded;
    update->metrics["alcazar.session.total_uploaded[counter]"] = total_uploaded;

    logger.debug("Updating session stats");
    SqliteStatement stmt = SqliteStatement(
            this->db, "UPDATE sessionstats SET total_downloaded = ?001, total_uploaded = ?002");
    stmt.bind_int64(1, total_downloaded);
    stmt.bind_int64(2, total_uploaded);
    int num_changes = stmt.update();
    if (num_changes != 1) {
        logger.error("Save session stats affected %d rows!", num_changes);
    }
    logger.debug("Updated session stats");
}

void SessionWrapper::on_alert_session_stats(BatchTorrentUpdate *update, lt::session_stats_alert *alert) {
    logger.debug("Received session stats.");
    for (auto &item : this->metrics_names) {
        update->metrics[item.first] = alert->values[item.second];
    }
    // Piggyback a session stats update to post timers and update torrent count metrics
    update->timer_stats = this->timers.stats;
    this->calculate_torrent_count_metrics(update);
    this->update_session_stats(update);
}

void SessionWrapper::on_alert_torrent_finished(BatchTorrentUpdate *update, lt::torrent_finished_alert *alert) {
    // Short-circuit while we're still in the loading phase, otherwise this is too slow.
    if (this->num_loaded_initial_torrents < this->num_initial_torrents) {
        return;
    }
    auto status = alert->handle.status();
    if (logger.is_enabled_for(Logger::DEBUG)) {
        logger.debug("Update torrent finished for %s.", lt::to_hex(status.info_hash.to_string()).c_str());
    }

    /* Copied explanation from Deluge:
     * Only save resume data if it was actually downloaded something. Helps
     * on startup with big queues with lots of seeding torrents. Libtorrent
     * emits alert_torrent_finished for them, but there seems like nothing
     * worth really to save in resume data, we just read it up in
     * self.load_state(). */
    if (status.total_payload_download) {
        int flags = lt::torrent_handle::only_if_modified;
        alert->handle.save_resume_data(flags);
    }
}

void SessionWrapper::on_alert_save_resume_data(BatchTorrentUpdate *update, lt::save_resume_data_alert *alert) {
    auto timer = this->timers.start_timer("on_alert_save_resume_data");
    auto info_hash = alert->handle.info_hash().to_string();
    if (logger.is_enabled_for(Logger::DEBUG)) {
        logger.debug("Received fast resume data for %s.", lt::to_hex(info_hash).c_str());
    }
    this->info_hashes_resume_data_wait.erase(info_hash);

    auto state_item = this->torrent_states.find(info_hash);
    if (state_item == this->torrent_states.end()) {
        logger.error("Received fast resume data for a torrent not in torrent_states.");
        return;
    }

    std::string resume_data;
    lt::bencode(std::back_inserter(resume_data), *alert->resume_data);
    SqliteStatement stmt = SqliteStatement(this->db, "UPDATE torrent SET resume_data = ?001 WHERE id = ?002");
    stmt.bind_blob(1, resume_data);
    stmt.bind_int64(2, state_item->second->row_id);
    int num_changes = stmt.update();
    if (num_changes != 1) {
        logger.error("Save resume data affected %d rows!", num_changes);
    }
}

void SessionWrapper::on_alert_save_resume_data_failed(
        BatchTorrentUpdate *update, lt::save_resume_data_failed_alert *alert) {
    auto timer = this->timers.start_timer("on_alert_save_resume_data_failed");
    auto info_hash = alert->handle.info_hash().to_string();
    if (logger.is_enabled_for(Logger::DEBUG)) {
        logger.debug("Received fast resume data failed for %s.", lt::to_hex(info_hash).c_str());
    }
    this->info_hashes_resume_data_wait.erase(info_hash);
    if (alert->error == lt::errors::resume_data_not_modified) {
        return;
    }
    logger.error("Received fast resume data failed for %s.", lt::to_hex(info_hash).c_str());
}

void SessionWrapper::on_alert_tracker_announce(BatchTorrentUpdate *update, lt::tracker_announce_alert *alert) {
    auto info_hash = alert->handle.info_hash().to_string();
    if (logger.is_enabled_for(Logger::DEBUG)) {
        logger.debug("Received tracker announce for %s.", lt::to_hex(info_hash).c_str());
    }
    auto state_item = this->torrent_states.find(info_hash);
    if (state_item != this->torrent_states.end() && state_item->second->update_tracker_announce()) {
        update->updated.push_back(state_item->second);
    } else {
        auto existing_state_item = this->pre_load_tracker_states.find(info_hash);
        std::string tracker_error;
        if (existing_state_item != this->pre_load_tracker_states.end()) {
            tracker_error = existing_state_item->second.tracker_error;
        }
        this->pre_load_tracker_states[info_hash] = TrackerTorrentState{TRACKER_STATUS_ANNOUNCING, tracker_error};
    }
}

void SessionWrapper::on_alert_tracker_reply(BatchTorrentUpdate *update, lt::tracker_reply_alert *alert) {
    auto info_hash = alert->handle.info_hash().to_string();
    if (logger.is_enabled_for(Logger::DEBUG)) {
        logger.debug("Received tracker reply for %s.", lt::to_hex(info_hash).c_str());
    }
    auto state_item = this->torrent_states.find(info_hash);
    if (state_item != this->torrent_states.end() && state_item->second->update_tracker_reply()) {
        update->updated.push_back(state_item->second);
    } else {
        this->pre_load_tracker_states[info_hash] = TrackerTorrentState{TRACKER_STATUS_SUCCESS, ""};
    }
}

void SessionWrapper::on_alert_tracker_error(BatchTorrentUpdate *update, lt::tracker_error_alert *alert) {
    auto info_hash = alert->handle.info_hash().to_string();
    if (logger.is_enabled_for(Logger::DEBUG)) {
        logger.debug("Received tracker error for %s.", lt::to_hex(info_hash).c_str());
    }
    auto state_item = this->torrent_states.find(info_hash);
    if (state_item != this->torrent_states.end() && state_item->second->update_tracker_error(alert)) {
        update->updated.push_back(state_item->second);
    } else {
        TrackerTorrentState tracker_torrent_state{TRACKER_STATUS_ERROR, format_tracker_error(alert)};
        this->pre_load_tracker_states[info_hash] = tracker_torrent_state;
    }
}

void SessionWrapper::on_alert_torrent_removed(BatchTorrentUpdate *update, lt::torrent_removed_alert *alert) {
    auto state_item = this->torrent_states.find(alert->info_hash.to_string());
    if (state_item == this->torrent_states.end()) {
        logger.error("Received torrent_removed_alert for torrent not in torrent_states.");
        return;
    }
    state_item->second->delete_db_row(this->db);
    update->removed.push_back(state_item->second);
    this->torrent_states.erase(state_item);
}

void SessionWrapper::on_alert_listen_succeeded(BatchTorrentUpdate *update, lt::listen_succeeded_alert *alert) {
    logger.info(alert->message().c_str());
    this->succeeded_listening = true;
}

void SessionWrapper::on_alert_listen_failed(BatchTorrentUpdate *update, lt::listen_failed_alert *alert) {
    logger.warning(alert->message().c_str());
}
