import asyncio
import base64
import json
import logging
import os
import subprocess
import time
import traceback
from asyncio import CancelledError

import transmissionrpc

from clients import Manager
from error_manager import Severity
from models import ManagedTransmissionConfig
from transmission import params
from transmission.executor import TransmissionAsyncExecutor
from transmission.torrent_state import TransmissionTorrentState
from utils import timezone_now

logger = logging.getLogger(__name__)


class ManagedTransmission(Manager):
    key = 'managed_transmission'
    config_model = ManagedTransmissionConfig

    def __init__(self, orchestrator, instance_config):
        super().__init__(orchestrator, instance_config)

        self._state_path = os.path.join(self.config.state_path, self._name)
        self._settings_path = os.path.join(self._state_path, 'settings.json')

        self._rpc_port = None
        self._process = None
        self._executor = None
        self._launch_datetime = None
        self._initialized = False
        self._torrent_states = {}
        # An unpleasant hack: when deleting torrents, an update could already be ongoing and a response can arrive
        # later, that includes the now deleted torrent. In order to avoid re-adding and re-deleting the torrent
        # we save the info hash here. We remove it from hereonce we receive an update without it so that it can be
        # re-added normally later
        self._deleted_info_hashes = set()

    @property
    def num_torrents(self):
        return len(self._torrent_states)

    @property
    def peer_port(self):
        return self._peer_port

    def _write_transmission_config(self):
        logger.debug('Writing transmission settings for {}'.format(self._name))
        result = dict(self.config.transmission_settings)
        result.update({
            'dht-enabled': self.config.is_dht_enabled,
            'rpc-port': self._rpc_port,
            'peer-port': self._peer_port,
            'rpc-username': 'transmission',
            'rpc-password': self.instance_config.rpc_password,
        })
        os.makedirs(self._state_path, exist_ok=True)
        with open(self._settings_path, 'w') as f:
            f.write(json.dumps(result, indent=4))

    def launch(self):
        logger.debug('Launching {}'.format(self._name))
        self._rpc_port = self._orchestrator.grab_local_port()
        self._peer_port = self._orchestrator.grab_peer_port()
        logger.debug('Received rpc_port={} and peer_port={} for {}'.format(self._rpc_port, self._peer_port, self._name))
        self._write_transmission_config()
        logger.info('Starting transmission-daemon for {}'.format(self._name))
        self._process = subprocess.Popen(['transmission-daemon', '-f', '-g', self._state_path])
        self._launch_datetime = timezone_now()
        self._executor = TransmissionAsyncExecutor(
            host='127.0.0.1',
            port=self._rpc_port,
            username='transmission',
            password=self.instance_config.rpc_password,
        )

        asyncio.ensure_future(self._loop())

    async def _loop(self):
        while True:
            start = time.time()

            try:
                await self._loop_iteration()
                self._initialized = True

                self._error_manager.clear_error(params.ERROR_KEY_LOOP)
                self._error_manager.clear_error(params.ERROR_KEY_OBTAIN_CLIENT, convert_errors_to_warnings=False)
            except CancelledError:
                break
            except Exception:
                self._error_manager.add_error(
                    severity=Severity.ERROR,
                    key=params.ERROR_KEY_LOOP,
                    message='Loop crashed',
                    traceback=traceback.format_exc()
                )
                logger.exception('Loop crashed')

            time_taken = time.time() - start
            logger.debug('Full update fetch for {} took {:.3f}'.format(self._name, time_taken))
            await asyncio.sleep(max(0, params.REFRESH_INTERVAL - time_taken))

    async def _loop_iteration(self):
        if not self._executor or not self._launch_datetime:
            raise Exception('Not launched yet')

        started = time.time()
        logger.debug('Starting full update for {}'.format(self._name))

        try:
            t_torrents = await self._executor.fetch_torrents()
        except transmissionrpc.TransmissionError:
            seconds_started = (timezone_now() - self._launch_datetime).total_seconds()
            if seconds_started <= params.STARTUP_TIMEOUT:
                self._error_manager.add_error(
                    severity=Severity.WARNING,
                    key=params.ERROR_KEY_OBTAIN_CLIENT,
                    message='Not connected to transmission yet',
                )
                logger.debug('Obtaining client failed, still within STARTUP_TIMEOUT.')
                return
            else:
                raise

        processing_start = time.time()

        self._initialized = True

        received_info_hashes = set()
        for t_torrent in t_torrents:
            received_info_hashes.add(t_torrent.hashString)

            # It was scheduled for deletion, so skip the update. We'll remove it once we get an update without it.
            if t_torrent.hashString in self._deleted_info_hashes:
                continue

            self._register_t_torrent_update(t_torrent)

        removed_info_hashes = set(self._torrent_states.keys()) - received_info_hashes
        for removed_info_hash in removed_info_hashes:
            self._register_t_torrent_delete(removed_info_hash)

        # Keep items in _deleted_info_hashes that are still being received
        self._deleted_info_hashes = self._deleted_info_hashes.intersection(received_info_hashes)

        end = time.time()
        logger.debug('Full update for {} complete in {}, processing in {}'.format(
            self._name, end - started, end - processing_start))

    def shutdown(self):
        logger.debug('Shutting down {}'.format(self._name))
        try:
            self._process.terminate()
            self._process.wait(params.SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.debug('transmission-daemon did not exit on time, killing {}...'.format(self._name))
            self._process.kill()

    def get_info_dict(self):
        data = super().get_info_dict()
        data.update({
            'pid': self._process.pid,
            'state_path': self._state_path,
            'rpc_port': self._rpc_port,
        })
        return data

    def get_debug_dict(self):
        data = super().get_debug_dict()
        data.update({
        })
        return data

    def _register_t_torrent_update(self, t_torrent):
        if t_torrent.hashString in self._torrent_states:
            torrent_state = self._torrent_states[t_torrent.hashString]
            if torrent_state.update_from_t_torrent(t_torrent):
                self._orchestrator.on_torrent_updated(torrent_state)
            return torrent_state
        else:
            torrent_state = TransmissionTorrentState(self, t_torrent)
            self._torrent_states[torrent_state.info_hash] = torrent_state
            self._orchestrator.on_torrent_added(torrent_state)
            return torrent_state

    def _register_t_torrent_delete(self, info_hash):
        del self._torrent_states[info_hash]
        self._orchestrator.on_torrent_removed(self, info_hash)

    async def add_torrent(self, torrent, download_path):
        if not self._initialized or not self._executor:
            message = 'Unable to add torrent in {}: not fully started up yet.'.format(self._name)
            logger.error(message)
            raise Exception(message)

        logger.info('Adding torrent in {}'.format(self._name))
        t_torrent = await self._executor.add_torrent(torrent, download_path)
        return self._register_t_torrent_update(t_torrent)

    async def delete_torrent(self, info_hash):
        if not self._initialized or not self._executor:
            message = 'Unable to delete torrent {} from {}: not fully started up yet.'.format(
                info_hash, self._name)
            logger.error(message)
            raise Exception(message)

        logger.info('Deleting torrent {} from {}'.format(info_hash, self._name))
        torrent_state = self._torrent_states[info_hash]
        await self._executor.delete_torrent(torrent_state.transmission_id)
        self._deleted_info_hashes.add(info_hash)
        self._register_t_torrent_delete(info_hash)
