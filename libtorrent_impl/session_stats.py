from clients import SessionStats


class LibtorrentSessionStats(SessionStats):
    def __init__(self, torrent_count, downloaded, uploaded, download_rate, upload_rate):
        super().__init__()
        self.torrent_count = torrent_count
        self.downloaded = downloaded
        self.uploaded = uploaded
        self.download_rate = download_rate
        self.upload_rate = upload_rate
