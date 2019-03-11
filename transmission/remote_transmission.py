import logging

from alcazar_logging import BraceAdapter
from models import RemoteTransmissionConfig
from transmission.base_transmission import BaseTransmission
from transmission.executor import TransmissionAsyncExecutor

logger = BraceAdapter(logging.getLogger(__name__))


class RemoteTransmission(BaseTransmission):
    key = 'remote_transmission'
    config_model = RemoteTransmissionConfig

    def __init__(self, orchestrator, instance_config):
        super().__init__(orchestrator, instance_config)

    @property
    def peer_port(self):
        return self._peer_port

    def launch(self):
        self._executor = TransmissionAsyncExecutor(
            host=self.instance_config.rpc_host,
            port=self.instance_config.rpc_port,
            username=self.instance_config.rpc_username,
            password=self.instance_config.rpc_password,
        )
        super().launch()

    def shutdown(self):
        pass
