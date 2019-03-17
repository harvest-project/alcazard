#ifndef TORRENTSTATE_HPP_
#define TORRENTSTATE_HPP_

#include <unordered_map>
#include <string>
#include <libtorrent/torrent_status.hpp>

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

class TorrentState {
public:

    std::string info_hash;
    Status status;
    std::string download_path;
    int64_t size;
    int64_t downloaded;
    int64_t uploaded;
    int64_t download_rate;
    int64_t upload_rate;
    double progress;
    std::string error;
    std::string tracker_error;

    TorrentState(lt::torrent_status *status);

    bool update_from_status(lt::torrent_status *status);
};

class BatchTorrentUpdate {
public:
    std::vector <lt::torrent_handle> added_handles;

    std::vector<TorrentState *> added;
    std::vector<TorrentState *> updated;
    std::vector <std::string> removed;

    std::unordered_map <std::string, uint64_t> metrics;
    std::unordered_map <std::string, TimerStat> timer_stats;
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

#endif
