from clients import SessionStats


class TransmissionSessionStats(SessionStats):
    def __init__(self, session_stats):
        super().__init__(
            torrent_count=session_stats.activeTorrentCount,
            downloaded=session_stats.cumulative_stats['downloadedBytes'],
            uploaded=session_stats.cumulative_stats['uploadedBytes'],
            download_rate=session_stats.downloadSpeed,
            upload_rate=session_stats.uploadSpeed,
        )
