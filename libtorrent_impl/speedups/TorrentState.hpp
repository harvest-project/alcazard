#ifndef TORRENTSTATE_HPP_
#define TORRENTSTATE_HPP_

#include <unordered_map>
#include <string>
#include <libtorrent/torrent_status.hpp>
#include <libtorrent/alert_types.hpp>

#include "Utils.hpp"

namespace lt = libtorrent;

// Values from clients.py
enum Status {
    STATUS_CHECK_WAITING = 0,
    STATUS_CHECKING = 1,
    STATUS_DOWNLOADING = 2,
    STATUS_SEEDING = 3,
    STATUS_STOPPED = 4
};

enum TrackerStatus {
    TRACKER_STATUS_PENDING = 0,
    TRACKER_STATUS_ANNOUNCING = 1,
    TRACKER_STATUS_SUCCESS = 2,
    TRACKER_STATUS_ERROR = 3,
    TRACKER_STATUS_MAX
};

struct TrackerTorrentState {
    TrackerStatus tracker_status;
    std::string tracker_error;
};

class TorrentState {
    static Logger logger;

public:
    lt::torrent_handle handle;

    int64_t row_id;
    std::string info_hash;
    TrackerStatus tracker_status;
    lt::torrent_status::state_t state;
    Status status;
    std::string name;
    std::string download_path;
    int64_t size;
    int64_t downloaded;
    int64_t uploaded;
    int64_t download_rate;
    int64_t upload_rate;
    double progress;
    std::string error;
    std::string tracker_error;
    time_t date_added;

    TorrentState(int64_t row_id, lt::torrent_status *status);
    void insert_db_row(sqlite3 *db, std::string torrent_file, std::string download_path, std::string *name_ptr);
    void delete_db_row(sqlite3 *db);
    bool update_from_status(lt::torrent_status *status);
    bool update_tracker_announce();
    bool update_tracker_reply();
    bool update_tracker_error(lt::tracker_error_alert *alert);
};

class BatchTorrentUpdate {
public:
    std::vector <std::shared_ptr<TorrentState>> added;
    std::vector <std::shared_ptr<TorrentState>> updated;
    std::vector <std::shared_ptr<TorrentState>> removed;

    std::unordered_map <std::string, uint64_t> metrics;
    std::unordered_map <std::string, TimerStat> timer_stats;
    int num_waiting_for_resume_data;
    bool succeeded_listening;

    std::vector<lt::save_resume_data_alert *> save_resume_data_alerts;
};

inline Status get_alcazar_status(lt::torrent_status::state_t state) {
    switch (state) {
        case lt::torrent_status::queued_for_checking:
            return STATUS_CHECK_WAITING;
        case lt::torrent_status::checking_files:
            return STATUS_CHECKING;
        case lt::torrent_status::downloading_metadata:
            return STATUS_DOWNLOADING;
        case lt::torrent_status::downloading:
            return STATUS_DOWNLOADING;
        case lt::torrent_status::finished:
            return STATUS_STOPPED;
        case lt::torrent_status::seeding:
            return STATUS_SEEDING;
        case lt::torrent_status::allocating:
            return STATUS_DOWNLOADING;
        case lt::torrent_status::checking_resume_data:
            return STATUS_CHECKING;
        default:
            throw std::runtime_error("Unknown torrent_status.state");
    }
}

extern std::unordered_map <std::string, std::string> host_from_url_cache;
std::string extract_host_from_url(std::string url);
std::string format_tracker_error(lt::tracker_error_alert *alert);

#endif
