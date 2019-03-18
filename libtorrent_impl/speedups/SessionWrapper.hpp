#ifndef SESSIONWRAPPER_HPP_
#define SESSIONWRAPPER_HPP_

#include <string>
#include <unordered_map>
#include <unordered_set>

#include <sqlite3.h>
#include <libtorrent/alert_types.hpp>
#include <libtorrent/session.hpp>
#include <libtorrent/settings_pack.hpp>
#include <libtorrent/add_torrent_params.hpp>

#include "TorrentState.hpp"
#include "Utils.hpp"

namespace lt = libtorrent;

class SessionWrapper {
private:
    int64_t config_id;
    libtorrent::session *session;
    sqlite3 *db;
    TimerAccumulator timers;
    int num_waiting_initial_torrents = 0;
    std::shared_ptr <Timer> timer_initial_torrents_received;
    std::vector <std::pair<std::string, int>> metrics_names;
    std::unordered_map <std::string, int64_t> added_torrent_row_ids;
    std::unordered_set <std::string> info_hashes_resume_data_wait;

    lt::settings_pack create_settings_pack();
    void init_metrics_names();
    void init_add_params(lt::add_torrent_params &params, std::string torrent, std::string download_path,
                         std::string *name, std::string *resume_data);
    std::shared_ptr <TorrentState> handle_torrent_added(lt::torrent_status *status);
    void calculate_torrent_count_metrics(BatchTorrentUpdate *update);
    void on_alert_add_torrent(BatchTorrentUpdate *update, lt::add_torrent_alert *alert);
    void on_alert_state_update(BatchTorrentUpdate *update, lt::state_update_alert *alert);
    void on_alert_session_stats(BatchTorrentUpdate *update, lt::session_stats_alert *alert);
    void on_alert_torrent_finished(BatchTorrentUpdate *update, lt::torrent_finished_alert *alert);
    void on_alert_save_resume_data(BatchTorrentUpdate *update, lt::save_resume_data_alert *alert);
    void on_alert_save_resume_data_failed(BatchTorrentUpdate *update, lt::save_resume_data_failed_alert *alert);
    void on_alert_tracker_announce(BatchTorrentUpdate *update, lt::tracker_announce_alert *alert);
    void on_alert_tracker_reply(BatchTorrentUpdate *update, lt::tracker_reply_alert *alert);
    void on_alert_tracker_error(BatchTorrentUpdate *update, lt::tracker_error_alert *alert);
    void on_alert_torrent_removed(BatchTorrentUpdate *update, lt::torrent_removed_alert *alert);

public:
    std::unordered_map <std::string, std::shared_ptr<TorrentState>> torrent_states;

    SessionWrapper(
            std::string db_path,
            int64_t config_id,
            std::string listen_interfaces,
            bool enable_dht
    );
    ~SessionWrapper();

    void load_initial_torrents();
    std::shared_ptr <TorrentState> add_torrent(
            std::string torrent,
            std::string download_path,
            std::string *name
    );
    void remove_torrent(std::string info_hash);
    void post_torrent_updates();
    void pause();
    BatchTorrentUpdate process_alerts();
    void post_session_stats();
    void all_torrents_save_resume_data(bool flush_cache);
};

#endif
