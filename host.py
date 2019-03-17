import asyncio
import logging
import os

from alcazar_logging import BraceAdapter
from api import AlcazarAPI
from migrations import apply_migrations
from models import DB, Config, MODELS
from orchestrator import AlcazarOrchestrator
from utils import DEFAULT_PORT

logger = BraceAdapter(logging.getLogger(__name__))


class AlcazarHost:
    def __init__(self, state_path):
        self.state_path = state_path
        self.db_path = os.path.join(state_path, 'db.sqlite3')

    def _init_db(self):
        DB.create_tables(MODELS)
        apply_migrations()

    def config(self, api_port):
        logger.info('Configuring alcazard with state at {}', self.state_path)

        api_port = api_port or DEFAULT_PORT

        os.makedirs(self.state_path, exist_ok=True)
        DB.init(self.db_path)

        with DB:
            self._init_db()

            config = Config.select().first()
            if not config:
                from transmission.params import DEFAULT_TRANSMISSION_SETTINGS_TEMPLATE
                config = Config(
                    is_fully_configured=True,
                    transmission_settings=DEFAULT_TRANSMISSION_SETTINGS_TEMPLATE,
                    is_dht_enabled=False,
                    local_port_pools_fmt='9091-9291',
                    peer_port_pools_fmt='21413-21613',
                )

            config.api_port = api_port
            config.save()

        logger.info('Saved configuration - done.')

    def run(self):
        logger.info('Starting alcazard with state at {}.', self.state_path)

        if not os.path.isfile(self.db_path):
            print('Missing state DB at {}! Exiting.'.format(self.db_path))
            exit(1)

        DB.init(self.db_path)
        DB.connect()
        self._init_db()

        config = Config.get()
        config.db_path = self.db_path
        config.state_path = self.state_path

        orchestrator = None
        if config.is_fully_configured:
            orchestrator = AlcazarOrchestrator(config)
            orchestrator.attach()

        api = AlcazarAPI(config, orchestrator)
        api.run()

        if orchestrator:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(orchestrator.shutdown())

        DB.close()

        logger.info('Graceful shutdown done.')
