STARTUP_TIMEOUT = 120
SHUTDOWN_TIMEOUT = 30
REFRESH_INTERVAL = 60

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
    'downloadedEver', 'uploadedEver', 'rateDownload', 'rateUpload']

ERROR_KEY_LOOP = 'loop'
ERROR_KEY_OBTAIN_CLIENT = 'obtain_client'
