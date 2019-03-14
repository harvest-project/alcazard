#include <string>

#include <sqlite3.h>
#include <libtorrent/session.hpp>
#include <libtorrent/settings_pack.hpp>

#include "SessionWrapper.hpp"

namespace lt = libtorrent;

SessionWrapper::SessionWrapper(
    std::string db_path,
    int config_id,
    std::string listen_interfaces,
    bool enable_dht) :

    config_id(config_id),
    session(NULL),
    db(NULL) {

    printf("Open sqlite3\n");
    if (sqlite3_open_v2(db_path.c_str(), &this->db, SQLITE_OPEN_READWRITE, NULL) != SQLITE_OK) {
        throw std::runtime_error("Error opening DB");
    }

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
        if (sqlite3_close_v2(this->db) != SQLITE_OK) {
            throw std::runtime_error("Error closing Sqlite3 DB");
        }
    }
}
