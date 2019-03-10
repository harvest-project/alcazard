import json
import logging
import os
import subprocess

from models import ManagedTransmissionConfig
from transmission.base_transmission import BaseTransmission
from transmission.executor import TransmissionAsyncExecutor

logger = logging.getLogger(__name__)


class ManagedTransmission(BaseTransmission):
    STARTUP_TIMEOUT = 120
    SHUTDOWN_TIMEOUT = 60

    key = 'managed_transmission'
    config_model = ManagedTransmissionConfig

    def __init__(self, orchestrator, instance_config):
        super().__init__(orchestrator, instance_config)

        self._state_path = os.path.join(self.config.state_path, self._name)
        self._settings_path = os.path.join(self._state_path, 'settings.json')

        self._rpc_port = None
        # Popen instance of the Transmission client
        self._process = None

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
        self._executor = TransmissionAsyncExecutor(
            host='127.0.0.1',
            port=self._rpc_port,
            username='transmission',
            password=self.instance_config.rpc_password,
        )
        super().launch()

    def shutdown(self):
        logger.debug('Shutting down {}'.format(self._name))
        try:
            self._process.terminate()
            self._process.wait(self.SHUTDOWN_TIMEOUT)
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
