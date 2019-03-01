import libtorrent

ALERT_MASK = (
        libtorrent.alert.category_t.error_notification |
        libtorrent.alert.category_t.tracker_notification |
        libtorrent.alert.category_t.status_notification

)

DHT_BOOTSTRAP_NODES = [
    'router.bittorrent.com:6881',
    'router.utorrent.com:6881',
    'router.bitcomet.com:6881',
    'dht.transmissionbt.com:6881',
    'dht.aelitis.com:6881',
]

LOOP_INTERVAL = 0.1
POST_UPDATES_INTERVAL = 3  # Post updates every 3 minutes
SAVE_RESUME_DATA_INTERVAL = 300  # Save resume data for all torrents (that need it) every 5 minutes
SHUTDOWN_TIMEOUT = 30


def get_session_settings(peer_port, enable_dht):
    _million = 10 ** 6
    return {
        # Client identification
        'user_agent': 'Deluge/{}'.format('1.2.15', '1.0.9.0'),
        'peer_fingerprint': '-DE13F0-',

        # Basic settings
        'alert_mask': ALERT_MASK,
        'listen_interfaces': '0.0.0.0:{0},[::]:{0}'.format(peer_port),
        'enable_dht': enable_dht,
        'dht_bootstrap_nodes': ','.join(DHT_BOOTSTRAP_NODES) if enable_dht else '',
        'alert_queue_size': _million,  # Ridiculous number. Hopefully enough to never drop alerts.
        'cache_size': 4096,  # 64MB in blocks of 16KiB
        'tick_interval': 1000,  # Maximum recommended tick length, saves CPU cycles
        'connections_limit': 1000,  # Default: 200, this is reasonably higher.
        'listen_queue_size': 32,  # Default: 5, higher recommended for higher performance clients
        'checking_mem_usage': 4096,  # Default 1024, in 16KiB blocks - higher = faster re-checks, more memory
        # Default: 4, for some aio backends, number of threads. Number of threads available for hashing is N/2 per
        # https://github.com/arvidn/libtorrent/issues/3005, so 8 should provide at least 2 hashing threads.
        'aio_threads': 8,
        'listen_system_port_fallback': False,  # Do not fall back to letting the OS pick a listening port.
        'max_retry_port_bind': 0,  # Do not allow trying port+1 when unable to bind
        'unchoke_slots_limit': 64,  # Number of unchoked peers, essentially seeding/downloading from.

        # Slow torrents
        'dont_count_slow_torrents': True,  # Torrents slower than below are not counted as (up/down)loading
        'inactive_down_rate': 10 * 1024,
        'inactive_up_rate': 10 * 1024,

        # Limits
        'active_downloads': 10,
        'active_seeds': _million,
        'active_checking': 1,
        'active_dht_limit': 1000,
        'active_tracker_limit': _million,
        'active_lsd_limit': _million,
        'active_limit': _million,
    }


ERROR_KEY_LOOP = 'loop'
ERROR_KEY_ALERT_PROCESSING = 'alert_processing_{}'
ERROR_KEY_PERIODIC_TASKS = 'periodic_tasks'
