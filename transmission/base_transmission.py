import asyncio
import datetime
import logging

from alcazar_logging import BraceAdapter
from clients import Manager, PeriodicTaskInfo
from transmission import params
from transmission.session_stats import TransmissionSessionStats
from transmission.torrent_state import TransmissionTorrentState
from utils import timezone_now

logger = BraceAdapter(logging.getLogger(__name__))


class BaseTransmission(Manager):
    STARTUP_TIMEOUT = 0

    def __init__(self, orchestrator, instance_config):
        super().__init__(orchestrator, instance_config)

        # Port where the instance is listening for peer connections
        self._rpc_port = None
        # Thread-based async executor to offload synchronous calls off the event thread
        self._executor = None
        # Map of info_hash: TransmissionTorrentStats, storing all the torrents we know about
        self._torrent_states = {}
        # How long the last full update took
        self._last_full_update_seconds = None
        # How long the last quick update took
        self._last_quick_update_seconds = None
        # Set of info hashes for quick update
        self._quick_update_info_hashes = set()

        # An unpleasant hack: when deleting torrents, an update could already be ongoing and a response can arrive
        # later, that includes the now deleted torrent. In order to avoid re-adding and re-deleting the torrent
        # we save the info hash here. We remove it from hereonce we receive an update without it so that it can be
        # re-added normally later
        self._deleted_info_hashes = set()

        self._periodic_tasks.append(PeriodicTaskInfo(self._full_update, params.INTERVAL_FULL_UPDATE))
        self._periodic_tasks.append(PeriodicTaskInfo(self._quick_update, params.INTERVAL_QUICK_UPDATE))
        self._periodic_tasks.append(PeriodicTaskInfo(self._session_update, params.INTERVAL_SESSION_UPDATE))

    @property
    def _launch_deadline(self):
        return self._launch_datetime + datetime.timedelta(seconds=self.STARTUP_TIMEOUT)

    def launch(self):
        super().launch()
        asyncio.ensure_future(self._loop())

    async def shutdown(self):
        pass

    async def _loop(self):
        while True:
            await self._run_periodic_tasks()
            await asyncio.sleep(params.INTERVAL_LOOP)

    async def _session_update(self):
        await self._executor.ensure_client(self._launch_deadline)
        session_stats = await self._executor.get_session_stats()
        self._session_stats = TransmissionSessionStats(session_stats)
        self._peer_port = session_stats.peer_port

    async def __update_torrents(self, info_hashes):
        requested_info_hashes = set(info_hashes) if info_hashes is not None else set(self._torrent_states.keys())

        await self._executor.ensure_client(self._launch_deadline)
        t_torrents = await self._executor.fetch_torrents(list(info_hashes) if info_hashes is not None else None)

        received_info_hashes = set()
        for t_torrent in t_torrents:
            received_info_hashes.add(t_torrent.hashString)

            # It was scheduled for deletion, so skip the update. We'll remove it once we get an update without it.
            if t_torrent.hashString in self._deleted_info_hashes:
                continue

            self._register_t_torrent_update(t_torrent)

        removed_info_hashes = requested_info_hashes - received_info_hashes
        for removed_info_hash in removed_info_hashes:
            self._register_t_torrent_delete(removed_info_hash)

        return received_info_hashes

    async def _full_update(self):
        logger.debug('Starting full update for {}', self._name)
        start = timezone_now()

        received_info_hashes = await self.__update_torrents(None)

        # Keep items in _deleted_info_hashes that are still being received
        self._deleted_info_hashes = self._deleted_info_hashes.intersection(received_info_hashes)

        if not self._initialized:
            self._initialize_time_seconds = (timezone_now() - self._launch_datetime).total_seconds()
            self._initialized = True
        self._last_full_update_seconds = (timezone_now() - start).total_seconds()

    async def _quick_update(self):
        logger.debug('Quick update hashes: {}', self._quick_update_info_hashes)
        if not self._quick_update_info_hashes:
            return

        logger.debug('Starting quick update for {}', self._name)
        start = timezone_now()

        await self.__update_torrents(self._quick_update_info_hashes)

        self._last_quick_update_seconds = (timezone_now() - start).total_seconds()

    def get_info_dict(self):
        data = super().get_info_dict()
        data.update({
        })
        return data

    def get_debug_dict(self):
        data = super().get_debug_dict()
        data.update({
            'torrents_in_quick_update': len(self._quick_update_info_hashes),
            'last_full_update_seconds': self._last_full_update_seconds,
            'last_quick_update_seconds': self._last_quick_update_seconds,
        })
        return data

    def _register_t_torrent_update(self, t_torrent):
        if t_torrent.hashString in self._torrent_states:
            torrent_state = self._torrent_states[t_torrent.hashString]
            if torrent_state.update_from_t_torrent(t_torrent):
                self._orchestrator.on_torrent_updated(self, torrent_state.to_dict())
        else:
            torrent_state = TransmissionTorrentState(self, t_torrent)
            self._torrent_states[torrent_state.info_hash] = torrent_state
            self._orchestrator.on_torrent_added(self, torrent_state.to_dict())

        if torrent_state.should_quick_update:
            torrent_state.last_quick_update = timezone_now()
            logger.debug('Add torrent {} for quick updating.', torrent_state.info_hash)
            self._quick_update_info_hashes.add(torrent_state.info_hash)
        elif torrent_state.info_hash in self._quick_update_info_hashes:
            secs_since_last = (timezone_now() - torrent_state.last_quick_update).total_seconds()
            if secs_since_last > params.QUICK_UPDATE_TIMEOUT:
                logger.debug('Remove torrent {} from quick updating.', torrent_state.info_hash)
                self._quick_update_info_hashes.remove(torrent_state.info_hash)

        return torrent_state

    def _register_t_torrent_delete(self, info_hash):
        if info_hash in self._torrent_states:
            del self._torrent_states[info_hash]
            self._quick_update_info_hashes.discard(info_hash)
            self._orchestrator.on_torrent_removed(self, info_hash)

    async def add_torrent(self, torrent, download_path, name):
        if not self._initialized:
            message = 'Unable to add torrent in {}: not fully started up yet.'.format(self._name)
            logger.error(message)
            raise Exception(message)

        logger.info('Adding torrent in {}', self._name)
        t_torrent = await self._executor.add_torrent(torrent, download_path, name)
        info_hash = t_torrent.hashString

        self._deleted_info_hashes.discard(info_hash)
        logger.debug('Adding new torrent {} for quick update.', info_hash)
        self._quick_update_info_hashes.add(info_hash)
        return self._register_t_torrent_update(t_torrent)

    async def delete_torrent(self, info_hash):
        if not self._initialized:
            message = 'Unable to delete torrent {} from {}: not fully started up yet.'.format(
                info_hash, self._name)
            logger.error(message)
            raise Exception(message)

        logger.info('Deleting torrent {} from {}', info_hash, self._name)
        torrent_state = self._torrent_states[info_hash]
        await self._executor.delete_torrent(torrent_state.transmission_id)
        self._deleted_info_hashes.add(info_hash)
        self._register_t_torrent_delete(info_hash)

    async def get_session_stats(self):
        return self._session_stats
