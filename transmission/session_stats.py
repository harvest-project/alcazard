from clients import SessionStats


class TransmissionSessionStats(SessionStats):
    def __init__(self, session_stats):
        super().__init__()
        self.torrent_count = session_stats.activeTorrentCount
        self.downloaded = session_stats.cumulative_stats['downloadedBytes']
        self.uploaded = session_stats.cumulative_stats['uploadedBytes']
        self.download_rate = session_stats.downloadSpeed
        self.upload_rate = session_stats.uploadSpeed
