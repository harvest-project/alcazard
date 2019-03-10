from clients import TorrentState, FieldInfo
from transmission.params import STATUS_MAPPING
from utils import extract_name_from_announce


def _get_tracker_errors(tracker_stats):
    for tracker_status in tracker_stats:
        if tracker_status['lastAnnounceResult'] == '':
            continue  # Still waiting
        elif tracker_status['lastAnnounceResult'] == 'Success':
            return None  # At least one tracker succeeded means the torrent is working
        else:
            return '{}: {}'.format(
                extract_name_from_announce(tracker_status['announce']),
                tracker_status['lastAnnounceResult'],
            )
    return None


class TransmissionTorrentState(TorrentState):
    _FIELD_MAPPING = [
        FieldInfo('name', 'name'),
        FieldInfo('status', 'status', converter=lambda s: STATUS_MAPPING[s]),
        FieldInfo('download_path', 'downloadDir'),
        FieldInfo('size', 'totalSize'),
        FieldInfo('downloaded', 'downloadedEver'),
        FieldInfo('uploaded', 'uploadedEver'),
        FieldInfo('download_rate', 'rateDownload'),
        FieldInfo('upload_rate', 'rateUpload'),
        FieldInfo('progress', 'percentDone'),
        FieldInfo('date_added', None, converter=lambda _: None),
        FieldInfo('error', 'errorString', converter=lambda x: x if x else None),
        FieldInfo('tracker_error', 'trackerStats', converter=_get_tracker_errors)
    ]

    def __init__(self, manager, t_torrent):
        super().__init__(manager, t_torrent.hashString)
        self.transmission_id = t_torrent.id
        self.update_from_t_torrent(t_torrent)

    def update_from_t_torrent(self, t_torrent):
        return self._sync_fields(t_torrent)
