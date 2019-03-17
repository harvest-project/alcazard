#include <string>

#include <libtorrent/torrent_status.hpp>

#include "TorrentState.hpp"

namespace lt = libtorrent;

#define UPDATE_STATE(A, B) { auto __temp = B; if (A != __temp) { A = __temp; updated = true; } }

TorrentState::TorrentState(int64_t row_id, lt::torrent_status *status)
        : handle(status->handle), row_id(row_id), tracker_status(TRACKER_STATUS_PENDING) {
    this->info_hash = status->info_hash.to_string();
    this->name = status->name;
    this->download_path = status->save_path;
    this->size = status->total_wanted;
    this->update_from_status(status);
}

bool TorrentState::update_from_status(lt::torrent_status *status) {
    bool updated = false;
    this->state = status->state;
    UPDATE_STATE(this->status, get_alcazar_status(status->state));
    UPDATE_STATE(this->size, status->total_wanted);
    UPDATE_STATE(this->downloaded, status->all_time_download);
    UPDATE_STATE(this->uploaded, status->all_time_upload);
    // Hack rates, as libtorrent seems to return very small values for a while after all transfer is complete
    UPDATE_STATE(this->download_rate, status->download_payload_rate <= 2 ? 0 : status->download_payload_rate);
    UPDATE_STATE(this->upload_rate, status->upload_payload_rate <= 2 ? 0 : status->upload_payload_rate);
    UPDATE_STATE(this->progress, status->progress);
    UPDATE_STATE(this->error, status->error);
    return updated;
}

bool TorrentState::update_tracker_announce() {
    bool updated = false;
    UPDATE_STATE(this->tracker_status, TRACKER_STATUS_ANNOUNCING);
    return updated;
}

bool TorrentState::update_tracker_reply() {
    bool updated = false;
    UPDATE_STATE(this->tracker_status, TRACKER_STATUS_SUCCESS);
    UPDATE_STATE(this->tracker_error, "");
    return updated;
}

bool TorrentState::update_tracker_error(lt::tracker_error_alert *alert) {


    bool updated = false;
    UPDATE_STATE(this->tracker_status, TRACKER_STATUS_ERROR);
    return updated;
}