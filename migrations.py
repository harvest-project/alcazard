import logging

import peewee
from playhouse import migrate

from alcazar_logging import BraceAdapter
from models import Migration, DB

logger = BraceAdapter(logging.getLogger(__name__))


def _migration_initial(migrator):
    pass


def _migration_add_libtorrent_download_upload(migrator):
    total_downloaded = peewee.BigIntegerField(default=0)
    total_uploaded = peewee.BigIntegerField(default=0)
    migrate.migrate(
        migrator.add_column('managedlibtorrentconfig', 'total_downloaded', total_downloaded),
        migrator.add_column('managedlibtorrentconfig', 'total_uploaded', total_uploaded),
    )


def _migration_add_libtorrent_torrent_name(migrator):
    name = peewee.TextField(null=True)
    migrate.migrate(
        migrator.add_column('libtorrenttorrent', 'name', name),
    )


MIGRATIONS = [
    ('0001_initial', _migration_initial),
    ('0002_add_libtorrent_download_upload', _migration_add_libtorrent_download_upload),
    ('0003_add_libtorrent_torrent_name', _migration_add_libtorrent_torrent_name),
]


@DB.atomic()
def _handle_table_creation():
    for migration_name, _ in MIGRATIONS:
        Migration(name=migration_name).save()


def _handle_migrations(current_migrations):
    migrator = migrate.SqliteMigrator(DB)
    for migration_name, migration_fn in MIGRATIONS:
        if migration_name in current_migrations:
            continue
        logger.info('Running migration {}', migration_name)
        with DB.atomic():
            migration_fn(migrator)
            Migration(name=migration_name).save()


def apply_migrations():
    current_migrations = {t[0] for t in Migration.select(Migration.name).tuples()}
    if len(current_migrations) == 0:  # Initial table creation, just insert all
        logger.info('Migrations table was just created, inserting all current migrations.')
        _handle_table_creation()
    else:
        logger.debug('Migrations detected, updating state.')
        _handle_migrations(current_migrations)
