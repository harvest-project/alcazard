import asyncio
import base64
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import transmissionrpc

from transmission.params import TRANSMISSION_FETCH_ARGS
from utils import TorrentFileInfo

logger = logging.getLogger(__name__)


class TransmissionAsyncExecutor:
    def __init__(self, host, port, username, password):
        self._host = host
        self._port = port
        self._username = username
        self._password = password

        self._thread_pool = ThreadPoolExecutor(2, 'transmission@{}:{}'.format(host, port))
        self._client = None

    # TODO: Replace with a thread-safe implementation using thread-local storage
    def _get_client(self):
        if self._client is None:
            logger.debug('Trying to obtain client for {}:{}'.format(self._host, self._port))
            self._client = transmissionrpc.Client(
                address=self._host,
                port=self._port,
                user=self._username,
                password=self._password,
                timeout=60,
            )
            logger.debug('Obtained client for {}:{}'.format(self._host, self._port))
        return self._client

    def _fetch_torrents(self):
        logger.debug('Fetching torrents from {}:{}'.format(self._host, self._port))
        client = self._get_client()
        return client.get_torrents(arguments=TRANSMISSION_FETCH_ARGS)

    async def fetch_torrents(self):
        return await asyncio.wrap_future(self._thread_pool.submit(self._fetch_torrents))

    def _add_torrent(self, torrent, download_path):
        logger.debug('Adding torrent to {}:{}'.format(self._host, self._port))
        client = self._get_client()
        base64_torrent = base64.b64encode(torrent).decode()
        torrent_file_info = TorrentFileInfo(torrent)
        if torrent_file_info.files is not None:
            # Multi-file torrent, that we'll need to rename after adding. If the destination is /a/b/c, we'll add it
            # to /a/b. Transmission will create /a/b/<torrent_name> and then we rename <torrent_name> to c.
            bootstrap_t_torrent = client.add_torrent(
                base64_torrent,
                download_dir=os.path.dirname(download_path),
                paused=True,
            )
            client.rename_torrent_path(
                bootstrap_t_torrent.id,
                torrent_file_info.name,
                os.path.basename(download_path),
            )
            client.start_torrent([bootstrap_t_torrent.id])
        else:
            # Single-file torrent or one that already, so just add it to download path. The file will be created inside.
            bootstrap_t_torrent = client.add_torrent(
                base64_torrent,
                download_dir=download_path,
                paused=False,
            )
        # Get the full object with all fields by the torrent id
        return client.get_torrent(bootstrap_t_torrent.id, arguments=TRANSMISSION_FETCH_ARGS)

    async def add_torrent(self, torrent, download_path):
        return await asyncio.wrap_future(self._thread_pool.submit(self._add_torrent, torrent, download_path))

    def _delete_torrent(self, t_id):
        logger.debug('Deleting torrent {} from {}:{}'.format(t_id, self._host, self._port))
        client = self._get_client()
        client.remove_torrent(t_id, delete_data=True)

    async def delete_torrent(self, t_id):
        return await asyncio.wrap_future(self._thread_pool.submit(self._delete_torrent, t_id))

    def _get_session_stats(self):
        logger.debug('Get session stats')
        client = self._get_client()
        return client.session_stats()

    async def get_session_stats(self):
        return await asyncio.wrap_future(self._thread_pool.submit(self._get_session_stats))
