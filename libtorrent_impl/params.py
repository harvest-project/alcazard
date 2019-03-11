import libtorrent

from clients import TorrentState

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

LOOP_INTERVAL = 0.1  # Interval in seconds between loop iterations (popping alerts)
SLOW_LOOP_THRESHOLD = 0.5  # Slower loops than this many seconds emits a warning
POST_UPDATES_INTERVAL = 3  # Post updates every 3 minutes
SAVE_RESUME_DATA_INTERVAL = 15 * 60  # Save resume data for all torrents (that need it) every 15 minutes
UPDATE_SESSION_STATS_INTERVAL = 3  # Interval in seconds for updating session stats
SHUTDOWN_TIMEOUT = 120  # Seconds to wait for alerts during shutdown to be processed

INITIAL_TORRENT_LOAD_BATCH_SIZE = 500  # Number of torrent in a batch when loading initial torrents into the session
INITIAL_TORRENT_LOAD_BATCH_SLEEP = 0.1  # Seconds to sleep between loading initial torrent batches

ALERT_BATCH_SIZE = 5000  # Alerts in a single processing batch transaction
ALERT_BATCH_SLEEP = 0.1  # Seconds to sleep between batches of ALERT_BATCH_SIZE to free up the event loop


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
        'alert_queue_size': _million * 4,  # 4 per torrent, in case we can't fetch any alerts while torrents are loading
        'cache_size': 4096,  # 64MB in blocks of 16KiB
        'tick_interval': 1000,  # Maximum recommended tick length, saves CPU cycles
        'connections_limit': 400,  # Default: 200, this is reasonably higher.
        'listen_queue_size': 32,  # Default: 5, higher recommended for higher performance clients
        'checking_mem_usage': 2048,  # Default 1024, in 16KiB blocks - higher = faster re-checks, more memory
        # Default: 4, for some aio backends, number of threads. Number of threads available for hashing is N/2 per
        # https://github.com/arvidn/libtorrent/issues/3005, so 8 should provide at least 2 hashing threads.
        'aio_threads': 8,
        'listen_system_port_fallback': False,  # Do not fall back to letting the OS pick a listening port.
        'max_retry_port_bind': 0,  # Do not allow trying port+1 when unable to bind
        'unchoke_slots_limit': 64,  # Number of unchoked peers, essentially seeding/downloading from.

        # Tracker scrape settings supporting large number of torrents
        'tracker_completion_timeout': 120,  # Up from a default of 30 secs
        'tracker_receive_timeout': 60,  # Up from a default of 10 secs
        'stop_tracker_timeout': 60,  # Up from a default of 5 secs, as all the torrents will want to stop

        # Slow torrents
        'dont_count_slow_torrents': True,  # Torrents slower than below are not counted as (up/down)loading
        'auto_manage_startup': 60,
        'inactive_down_rate': 10 * 1024,
        'inactive_up_rate': 10 * 1024,

        # Limits
        'active_downloads': 8,
        'active_seeds': -1,
        'active_checking': 32,  # TODO: HACK! Actually resolve why checking is slow.
        'active_dht_limit': 1000,
        'active_tracker_limit': -1,
        'active_lsd_limit': -1,
        'active_limit': -1,
    }


ERROR_KEY_LOOP = 'loop'
ERROR_KEY_ALERT_PROCESSING = 'alert_processing_{}'
ERROR_KEY_PERIODIC_TASKS = 'periodic_tasks'
ERROR_KEY_ALREADY_ADDED = 'torrent_already_added'

STATUS_MAPPING = {
    0: TorrentState.STATUS_CHECK_WAITING,  # queued_for_checking
    1: TorrentState.STATUS_CHECKING,  # checking_files
    2: TorrentState.STATUS_DOWNLOADING,  # downloading_metadata
    3: TorrentState.STATUS_DOWNLOADING,  # downloading
    4: TorrentState.STATUS_STOPPED,  # finished
    5: TorrentState.STATUS_SEEDING,  # seeding
    6: TorrentState.STATUS_DOWNLOADING,  # allocating
    7: TorrentState.STATUS_CHECKING,  # checking_resume_data
}


def get_torrent_add_params(torrent, download_path, name, resume_data):
    lt_torrent_info = libtorrent.torrent_info(libtorrent.bdecode(torrent))

    if name is not None:
        files = lt_torrent_info.files()
        files.set_name(name)

    add_params = {
        'ti': lt_torrent_info,
        'save_path': download_path,
        'storage_mode': libtorrent.storage_mode_t.storage_mode_sparse,
        'paused': False,
        'auto_managed': True,
        'duplicate_is_error': True,
        'flags': libtorrent.add_torrent_params_flags_t.default_flags |
                 libtorrent.add_torrent_params_flags_t.flag_update_subscribe,
    }
    if resume_data:
        add_params['resume_data'] = resume_data

    return add_params
