import json

import peewee
from playhouse import migrate
from playhouse.shortcuts import model_to_dict, update_model_from_dict

from utils import get_ports_from_ranges, parse_port_pools_fmt, generate_password

DB = peewee.SqliteDatabase(None)


class Config(peewee.Model):
    api_port = peewee.IntegerField()
    is_fully_configured = peewee.BooleanField()
    transmission_settings_json = peewee.TextField(null=True)
    is_dht_enabled = peewee.BooleanField(null=True)
    local_port_pools_fmt = peewee.TextField(null=True)
    peer_port_pools_fmt = peewee.TextField(null=True)
    clean_directories_on_remove = peewee.BooleanField(default=False)
    clean_torrent_file_on_remove = peewee.BooleanField(default=False)

    @property
    def transmission_settings(self):
        return json.loads(self.transmission_settings_json)

    @transmission_settings.setter
    def transmission_settings(self, value):
        self.transmission_settings_json = json.dumps(value, indent=4, sort_keys=True)

    @property
    def local_ports(self):
        return get_ports_from_ranges(parse_port_pools_fmt(self.local_port_pools_fmt))

    @property
    def peer_ports(self):
        return get_ports_from_ranges(parse_port_pools_fmt(self.peer_port_pools_fmt))

    def to_dict(self):
        return model_to_dict(self, recurse=False, exclude=(Config.id,))

    def update_from_dict(self, data):
        update_model_from_dict(self, data)

    class Meta:
        database = DB


class Realm(peewee.Model):
    name = peewee.TextField()

    class Meta:
        database = DB


class ManagerConfig(peewee.Model):
    realm = peewee.ForeignKeyField(Realm, backref='managed_transmissions')


class ManagedTransmissionConfig(ManagerConfig, peewee.Model):
    rpc_password = peewee.TextField()

    def to_dict(self):
        result = model_to_dict(self, exclude=(ManagedTransmissionConfig.realm,), recurse=False)
        result['realm'] = self.realm.name
        return result

    @classmethod
    def create_new(cls, realm):
        return cls.create(
            realm=realm,
            rpc_password=generate_password(16),
        )

    class Meta:
        database = DB


class RemoteTransmissionConfig(ManagerConfig, peewee.Model):
    rpc_host = peewee.TextField()
    rpc_port = peewee.IntegerField()
    rpc_username = peewee.TextField()
    rpc_password = peewee.TextField()

    def to_dict(self):
        result = model_to_dict(self, exclude=(ManagedTransmissionConfig.realm,), recurse=False)
        result['realm'] = self.realm.name
        return result

    @classmethod
    def create_new(cls, realm, rpc_host, rpc_port, rpc_username, rpc_password):
        return cls.create(
            realm=realm,
            rpc_host=rpc_host,
            rpc_port=rpc_port,
            rpc_username=rpc_username,
            rpc_password=rpc_password,
        )

    class Meta:
        database = DB


class ManagedLibtorrentConfig(ManagerConfig, peewee.Model):
    total_downloaded = peewee.BigIntegerField()
    total_uploaded = peewee.BigIntegerField()

    def to_dict(self):
        result = model_to_dict(self, exclude=(ManagedTransmissionConfig.realm,), recurse=False)
        result['realm'] = self.realm.name
        return result

    @classmethod
    def create_new(cls, realm):
        return cls.create(
            realm=realm,
            total_downloaded=0,
            total_uploaded=0,
        )

    class Meta:
        database = DB


class Migration(peewee.Model):
    name = peewee.CharField(max_length=256)

    class Meta:
        database = DB


MODELS = [
    Config,
    Realm,
    ManagedTransmissionConfig,
    RemoteTransmissionConfig,
    ManagedLibtorrentConfig,
    Migration,
]


def _add_config_clean_options(migrator):
    clean_directories_on_remove = peewee.BooleanField(default=False)
    clean_torrent_file_on_remove = peewee.BooleanField(default=False)
    migrate.migrate(
        migrator.add_column('config', 'clean_directories_on_remove', clean_directories_on_remove),
        migrator.add_column('config', 'clean_torrent_file_on_remove', clean_torrent_file_on_remove),
    )


MIGRATIONS = [
    ('0001_initial', lambda: None),
    ('0002_add_config_clean_options', _add_config_clean_options),
]
