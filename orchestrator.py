import asyncio
import logging
from asyncio import CancelledError
from collections import defaultdict, Counter

from alcazar_logging import BraceAdapter
from clients import get_manager_types, TorrentNotFoundException
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
        self.managers = {}
        self.managers_by_realm = defaultdict(list)
        self.realm_info_hash_to_manager = defaultdict(dict)
        self.pooled_updates = {}
        self.pooled_removes = set()

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
                await self._run_iter()
                await asyncio.sleep(0.5)
        except CancelledError:
            pass

    async def _run_iter(self):
        print('Iter :)')

    def shutdown(self):
        logger.info('Shutting down orchestrator now...')
        for manager in self.managers.values():
            try:
                manager.shutdown()
            except Exception:
                logger.exception('Manager failed shutdown')
        logger.info('Clients are down.')

    def _load_manager_for_config(self, manager_class, instance_config):
        if __debug__:
            logger.debug('Launching manager {} for config id={}', manager_class.__name__, instance_config.id)
        manager = manager_class(self, instance_config)
        manager.launch()
        self.managers[manager.name] = manager
        self.managers_by_realm[instance_config.realm_id].append(manager)
        return manager

    @DB.atomic()
    def add_instance(self, realm, instance_type, config_kwargs):
        logger.info('Adding instance {} to realm {}', instance_type, realm.name)
        manager = self.manager_types[instance_type]
        instance_config = manager.config_model.create_new(realm=realm, **config_kwargs)
        instance = self._load_manager_for_config(manager, instance_config)
        return instance

    async def add_torrent(self, realm, torrent, download_path, name):
        logger.info('Adding torrent to realm {}', realm)
        # Get the managers that we're interested in (chosen realm)
        realm_managers = self.managers_by_realm[realm.id]
        if not realm_managers:
            raise NoManagerForRealmException()
        # Get a dict {manager: count} for the torrent counts
        torrent_counts = Counter(self.realm_info_hash_to_manager[realm.id].values())
        # Choose the manager with the smallest count from torrent_counts
        manager = min(realm_managers, key=lambda m: torrent_counts.get(m, 0))
        return await manager.add_torrent(torrent, download_path, name)

    async def delete_torrent(self, realm, info_hash):
        logger.info('Deleting torrent {} from realm {}', info_hash, realm)
        manager = self.realm_info_hash_to_manager[realm.id].get(info_hash)
        if not manager:
            raise TorrentNotFoundException()
        await manager.delete_torrent(info_hash)

    def on_torrent_added(self, manager, data):
        if __debug__:
            logger.debug('Received torrent added from {} for {}', manager.name, data['info_hash'])

        realm_id = manager.instance_config.realm_id
        self.realm_info_hash_to_manager[realm_id][data['info_hash']] = manager
        # For now, treat adds as updates, the difference is min
        self.on_torrent_updated(manager, data)

    def on_torrent_updated(self, manager, data):
        if __debug__:
            logger.debug('Received torrent update from {} for {}', manager.name, data['info_hash'])

        realm = manager.instance_config.realm
        self.pooled_updates[data['info_hash']] = data
        # Remove potential entries in pooled_removes, in case it's re-added before updates are fetched
        self.pooled_removes.discard((realm.name, data['info_hash']))

    def on_torrent_removed(self, manager, info_hash):
        if __debug__:
            logger.debug('Received torrent delete from {} for {}', manager.name, info_hash)

        realm = manager.instance_config.realm

        del self.realm_info_hash_to_manager[realm.id][info_hash]
        # Discard any pooled updates we've had for this torrent
        if info_hash in self.pooled_updates:
            del self.pooled_updates[info_hash]
        self.pooled_removes.add((realm.name, info_hash))

    def pop_pooled_updates(self, limit):
        if limit >= len(self.pooled_updates):
            updates = list(self.pooled_updates.values())
            self.pooled_updates.clear()
        else:
            updates = []
            for _ in range(limit):
                updates.append(self.pooled_updates.popitem()[1])
        return updates

    def pop_pooled_removes(self):
        removes = list(self.pooled_removes)
        self.pooled_removes.clear()
        return removes
