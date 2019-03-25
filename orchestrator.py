import asyncio
import logging
from asyncio import CancelledError
from collections import defaultdict, Counter

from alcazar_logging import BraceAdapter
from clients import get_manager_types, TorrentNotFoundException, TorrentBatchUpdate
from models import DB

logger = BraceAdapter(logging.getLogger(__name__))


class NoManagerForRealmException(Exception):
    pass


class AlcazarOrchestrator:
    def __init__(self, config):
        self.config = config
        self.available_local_ports = config.local_ports
        self.available_peer_ports = config.peer_ports

        self.manager_types = get_manager_types()
        self.managers_by_realm = defaultdict(list)
        self.realm_by_id = {}

        self.realm_info_hash_manager = defaultdict(dict)
        self.realm_accumulated_batch = defaultdict(TorrentBatchUpdate)

    def grab_local_port(self):
        return self.available_local_ports.pop()

    def grab_peer_port(self):
        return self.available_peer_ports.pop()

    def attach(self):
        for manager_class in self.manager_types.values():
            if __debug__:
                logger.debug('Launching managers for {}', manager_class.__name__)
            config_type = manager_class.config_model
            for instance_config in config_type.select().order_by(config_type.id):
                self._load_manager_for_config(manager_class, instance_config)

        asyncio.ensure_future(self._run())

    async def _run(self):
        try:
            while True:
                logger.debug('Iter :)')
                await asyncio.sleep(0.2)
        except CancelledError:
            pass

    async def shutdown(self):
        logger.info('Shutting down orchestrator now...')
        tasks = []
        for managers in self.managers_by_realm.values():
            for manager in managers:
                tasks.append(manager.shutdown())
        await asyncio.gather(*tasks)
        logger.info('Clients are down.')

    def _load_manager_for_config(self, manager_class, instance_config):
        if __debug__:
            logger.debug('Launching manager {} for config id={}', manager_class.__name__, instance_config.id)
        manager = manager_class(self, instance_config)
        manager.launch()
        self.managers_by_realm[instance_config.realm.id].append(manager)
        self.realm_by_id[instance_config.realm.id] = instance_config.realm
        return manager

    @DB.atomic()
    def add_instance(self, realm, instance_type, config_kwargs):
        logger.info('Adding instance {} to realm {}.', instance_type, realm.name)
        self.realm_by_id[realm.id] = realm
        manager = self.manager_types[instance_type]
        instance_config = manager.config_model.create_new(realm=realm, **config_kwargs)
        instance = self._load_manager_for_config(manager, instance_config)
        logger.info('Created and started instance {}.'.format(instance.name))
        return instance

    async def add_torrent(self, realm, torrent_file, download_path, name):
        logger.info('Adding torrent to realm {}', realm)
        # Get the managers that we're interested in (chosen realm)
        realm_managers = self.managers_by_realm[realm.id]
        if not realm_managers:
            raise NoManagerForRealmException()
        # Get a dict {manager: count} for the torrent counts
        torrent_counts = Counter(self.realm_info_hash_manager[realm.id].values())
        # Choose the manager with the smallest count from torrent_counts
        manager = min(realm_managers, key=lambda m: torrent_counts.get(m, 0))
        return await manager.add_torrent(torrent_file, download_path, name)

    async def remove_torrent(self, realm, info_hash):
        logger.info('Removing torrent {} from realm {}', info_hash, realm)
        manager = self.realm_info_hash_manager[realm.id].get(info_hash)
        if not manager:
            raise TorrentNotFoundException()
        if not manager.initialized:
            raise Exception('Trying to remove a torrent from a manager that is not fully initialized.')
        await manager.remove_torrent(info_hash)

    def on_torrent_batch_update(self, manager, batch):
        logger.debug('Orchestrator received batch update with {} adds, {} updates and {} deletes'.format(
            len(batch.added), len(batch.updated), len(batch.removed)))
        realm_id = manager.instance_config.realm_id
        info_hash_manager = self.realm_info_hash_manager[realm_id]

        self.realm_accumulated_batch[realm_id].update(batch)

        for info_hash in batch.added.keys():
            info_hash_manager[info_hash] = manager
        for info_hash in batch.removed:
            info_hash_manager.pop(info_hash, None)

    def pop_update_batch_dicts(self, limit):
        result = {}
        for realm_id, accumulated_batch in self.realm_accumulated_batch.items():
            realm = self.realm_by_id[realm_id]
            batch, limit = accumulated_batch.pop_batch(limit)
            result[realm.name] = batch.to_dict()
        return result
