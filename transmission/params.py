from clients import TorrentState

INTERVAL_FULL_UPDATE = 300
INTERVAL_QUICK_UPDATE = 3
INTERVAL_SESSION_UPDATE = 3

QUICK_UPDATE_TIMEOUT = 30

DEFAULT_TRANSMISSION_SETTINGS_TEMPLATE = {
    'peer-limit-global': 1000,
    'peer-limit-per-torrent': 120,
    'port-forwarding-enabled': False,
    'rpc-authentication-required': True,
    'rpc-host-whitelist-enabled': False,
    'upload-slots-per-torrent': 64,
}

TRANSMISSION_FETCH_ARGS = [
    'id', 'name', 'hashString', 'totalSize', 'uploadedEver', 'percentDone', 'addedDate', 'errorString', 'downloadDir',
    'downloadedEver', 'uploadedEver', 'rateDownload', 'rateUpload', 'status', 'trackerStats']

ERROR_KEY_LOOP = 'loop'
ERROR_KEY_OBTAIN_CLIENT = 'obtain_client'

STATUS_MAPPING = {
    'stopped': TorrentState.STATUS_STOPPED,
    'check pending': TorrentState.STATUS_CHECK_WAITING,
    'checking': TorrentState.STATUS_CHECKING,
    'download pending': TorrentState.STATUS_STOPPED,
    'downloading': TorrentState.STATUS_DOWNLOADING,
    'seed pending': TorrentState.STATUS_STOPPED,
    'seeding': TorrentState.STATUS_SEEDING,
}

QUICK_UPDATE_STATUSES = {
    TorrentState.STATUS_CHECK_WAITING,
    TorrentState.STATUS_CHECKING,
    TorrentState.STATUS_DOWNLOADING,
}
