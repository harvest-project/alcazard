from clients import TorrentState, FieldInfo
from libtorrent_impl.params import STATUS_MAPPING
from libtorrent_impl.utils import LibtorrentClientException, format_tracker_error
from models import LibtorrentTorrent


def _convert_status(state):
    return STATUS_MAPPING[int(state)]


class LibtorrentTorrentState(TorrentState):
    TRACKER_PENDING = 0
    TRACKER_ANNOUNCING = 1
    TRACKER_SUCCESS = 2
    TRACKER_ERROR = 3

    _FIELD_MAPPING = [
        FieldInfo('name', 'name'),
        FieldInfo('status', 'state', converter=_convert_status),
        FieldInfo('download_path', 'save_path'),
        FieldInfo('size', 'total_wanted'),
        FieldInfo('downloaded', 'all_time_download'),
        FieldInfo('uploaded', 'all_time_upload'),
        # Work around weird issue where libtorrent returns 1 byte/s for a long time
        FieldInfo('download_rate', 'download_payload_rate', converter=lambda i: i if i > 1 else 0),
        FieldInfo('upload_rate', 'upload_payload_rate', converter=lambda i: i if i > 1 else 0),
        FieldInfo('progress', 'progress'),
        FieldInfo('date_added', None, converter=lambda _: None),
        FieldInfo('error', 'error', converter=lambda i: i or None),
        FieldInfo('state', 'state', converter=str, public=False),
    ]

    def __init__(self, manager, handle, *, torrent_file=None, download_path=None, db_torrent=None):
        status = handle.status()

        super().__init__(manager, str(status.info_hash))

        self.handle = handle
        self.state = None
        self.tracker_status = self.TRACKER_PENDING

        if db_torrent:
            self.db_torrent = db_torrent
        else:
            self.db_torrent = self._load_or_create_db_torrent(torrent_file, download_path)

        self.update_from_status(handle.status())

    def _load_or_create_db_torrent(self, torrent_file, download_path):
        try:
            return LibtorrentTorrent.select().where(
                LibtorrentTorrent.libtorrent == self.manager.instance_config,
                LibtorrentTorrent.info_hash == self.info_hash,
            ).get()
        except LibtorrentTorrent.DoesNotExist:
            if not torrent_file or not download_path:
                raise LibtorrentClientException(
                    'Creating a new LibtorrentTorrent without supplying torrent_file and download_path.')
            return LibtorrentTorrent.create(
                libtorrent=self.manager.instance_config,
                info_hash=self.info_hash,
                torrent_file=torrent_file,
                download_path=download_path,
                resume_data=None,  # To be filled in later from the main thread
            )

    def delete(self):
        self.db_torrent.delete_instance()

    def update_from_status(self, status):
        if __debug__:
            if self.info_hash != str(status.info_hash):
                raise LibtorrentClientException('Updating wrong TorrentStatus')
        return self._sync_fields(status)

    def update_tracker_success(self):
        self.tracker_status = self.TRACKER_SUCCESS

        if self.tracker_error:
            self.tracker_error = None
            return True
        return False

    def update_tracker_error(self, alert):
        self.tracker_status = self.TRACKER_ERROR

        tracker_error = format_tracker_error(alert)
        if self.tracker_error != tracker_error:
            self.tracker_error = tracker_error
            return True
        return False

    def to_dict(self):
        result = super().to_dict()
        result['tracker_error'] = self.tracker_error
        return result
