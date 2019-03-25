from clients import TorrentState

DHT_BOOTSTRAP_NODES = [
    'router.bittorrent.com:6881',
    'router.utorrent.com:6881',
    'router.bitcomet.com:6881',
    'dht.transmissionbt.com:6881',
    'dht.aelitis.com:6881',
]

LOOP_INTERVAL = 0.2  # Interval in seconds between loop iterations (popping alerts)
SLOW_LOOP_THRESHOLD = 0.5  # Slower loops than this many seconds emits a warning
POST_UPDATES_INTERVAL = 3  # Post updates every 3 minutes
SAVE_RESUME_DATA_INTERVAL = 15 * 60  # Save resume data for all torrents (that need it) every 15 minutes
UPDATE_SESSION_STATS_INTERVAL = 1  # Interval in seconds for updating session stats
SHUTDOWN_TIMEOUT = 300  # Seconds to wait for alerts during shutdown to be processed

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
