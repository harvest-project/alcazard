from clients import TorrentState, FieldInfo


class TransmissionTorrentState(TorrentState):
    _FIELD_MAPPING = [
        FieldInfo('name', 'name'),
        FieldInfo('download_path', 'downloadDir'),
        FieldInfo('size', 'totalSize'),
        FieldInfo('downloaded', 'downloadedEver'),
        FieldInfo('uploaded', 'uploadedEver'),
        FieldInfo('download_rate', 'rateDownload'),
        FieldInfo('upload_rate', 'rateUpload'),
        FieldInfo('progress', 'percentDone'),
        FieldInfo('date_added', None, converter=lambda _: None),
        FieldInfo('error', 'errorString', converter=lambda x: x if x else None),
    ]

    def __init__(self, manager, t_torrent):
        super().__init__(manager, t_torrent.hashString)
        self.transmission_id = t_torrent.id
        self._sync_fields(t_torrent)

    def update_from_t_torrent(self, t_torrent):
        return self._sync_fields(t_torrent)
