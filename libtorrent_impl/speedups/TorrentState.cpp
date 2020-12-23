#include <string>

#include <libtorrent/torrent_status.hpp>
#include <sqlite3.h>

#include "yuarel.hpp"
#include "SqliteHelper.hpp"
#include "TorrentState.hpp"

namespace lt = libtorrent;

Logger TorrentState::logger("TorrentState");

#define UPDATE_STATE(A, B) { auto __temp = B; if (A != __temp) { A = __temp; updated = true; } }

TorrentState::TorrentState(int64_t row_id, lt::torrent_status *status)
        : handle(status->handle)
        , row_id(row_id)
        , tracker_status(TRACKER_STATUS_PENDING)
        , status(STATUS_CHECK_WAITING)
        , downloaded(0)
        , uploaded(0)
        , download_rate(0)
        , upload_rate(0)
        , progress(0)
        , error("")
        , tracker_error("")
        , date_added(0) {
    this->info_hash = status->info_hash.to_string();
    this->name = status->name;
    this->download_path = status->save_path;
    this->size = status->total_wanted;
    this->update_from_status(status);
}

void TorrentState::insert_db_row(sqlite3 *db, std::string torrent_file, std::string download_path,
                                 std::string *name_ptr) {
    SqliteStatement stmt = SqliteStatement(
            db, "INSERT INTO torrent (info_hash, torrent_file, download_path, name) VALUES (?001, ?002, ?003, ?004)");

    std::string name;
    std::string info_hash_str = lt::to_hex(this->info_hash);

    stmt.bind_blob(1, info_hash_str.c_str());
    stmt.bind_blob(2, torrent_file);
    stmt.bind_text(3, download_path);
    if (name_ptr) {
        name = *name_ptr;
        stmt.bind_text(4, name.c_str());
    }
    this->row_id = stmt.insert();
}

void TorrentState::delete_db_row(sqlite3 *db) {
    if (this->row_id == -1) {
        TorrentState::logger.error("Trying to delete_db_row for TorrentState with id -1.");
        return;
    }
    SqliteStatement stmt = SqliteStatement(db, "DELETE FROM torrent WHERE id = ?001");
    stmt.bind_int64(1, this->row_id);
    stmt.exec();
    this->row_id = -1;
}

bool TorrentState::update_from_status(lt::torrent_status *status) {
    bool updated = false;
    this->state = status->state;
    UPDATE_STATE(this->status, get_alcazar_status(status->state));
    // Status must be stopped since it is paused
    // Alternative 'cleaner' solution would be to add a paused attribute and update that
    if (status->paused) {
        UPDATE_STATE(this->status, STATUS_STOPPED);
    }
    UPDATE_STATE(this->size, status->total_wanted);
    UPDATE_STATE(this->downloaded, status->all_time_download);
    UPDATE_STATE(this->uploaded, status->all_time_upload);
    // Hack rates, as libtorrent seems to return very small values for a while after all transfer is complete
    UPDATE_STATE(this->download_rate, status->download_payload_rate <= 2 ? 0 : status->download_payload_rate);
    UPDATE_STATE(this->upload_rate, status->upload_payload_rate <= 2 ? 0 : status->upload_payload_rate);
    UPDATE_STATE(this->progress, status->progress);
    UPDATE_STATE(this->error, status->error);
    UPDATE_STATE(this->date_added, status->added_time);
    return updated;
}

bool TorrentState::update_file_name(std::string name) {
    bool updated = false;
    UPDATE_STATE(this->name, name);
    return updated;
}

bool TorrentState::update_download_path(std::string download_path) {
    bool updated = false;
    UPDATE_STATE(this->download_path, download_path);
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
    // When pausing, there is a connection lost alert
    // This should be suppressed so the client shows paused instead of stopped with error
    if (this->handle.status().paused) {
        return false;   
    }
    UPDATE_STATE(this->tracker_status, TRACKER_STATUS_ERROR);
    UPDATE_STATE(this->tracker_error, format_tracker_error(alert));
    return updated;
}

std::unordered_map <std::string, std::string> host_from_url_cache;

std::string extract_host_from_url(std::string url) {
    auto cache_item = host_from_url_cache.find(url);
    if (cache_item != host_from_url_cache.end()) {
        return cache_item->second;
    }

    char buffer[url.size() + 1];
    url.copy(buffer, url.size());
    buffer[url.size()] = 0;

    yuarel y_url;
    std::string result;
    if (yuarel_parse(&y_url, buffer) == -1) {
        result = url;
    }
    if (y_url.host) {
        result = std::string(y_url.host);
    } else {
        result = url;
    }

    return host_from_url_cache[url] = result;
}

std::string format_tracker_error(lt::tracker_error_alert *alert) {

    std::string host = extract_host_from_url(std::string(alert->tracker_url()));
    std::string errormessage = alert->error.message();
    // Ugliest UTF-8 safe first letter uppercase code
    if (errormessage[0] >= 32 && errormessage[0] < 128) {
        errormessage[0] = std::toupper(errormessage[0]);
    }

    char buffer[400];

    snprintf(
            buffer,
            sizeof(buffer) / sizeof(buffer[0]),
            "%s - %s (%s)",
            errormessage.c_str(),
            alert->error_message(),
            host.c_str()
    );

    return std::string(buffer);
}
