import logging

from playhouse import migrate

from alcazar_logging import BraceAdapter

logger = BraceAdapter(logging.getLogger(__name__))


def _record_migration(db, name):
    db.execute_sql('INSERT INTO migration (name) VALUES (?001)', (name,))


def _handle_table_creation(db, migrations):
    with db.atomic():
        for migration_name, _ in migrations:
            _record_migration(db, migration_name)


def _handle_migrations(db, migrations, current_migrations):
    migrator = migrate.SqliteMigrator(db)
    for migration_name, migration_fn in migrations:
        if migration_name in current_migrations:
            continue
        logger.info('Running migration {}', migration_name)
        with db.atomic():
            migration_fn(migrator)
            _record_migration(db, migration_name)


def apply_migrations(db, models, migrations):
    db.create_tables(models)
    current_migrations = {t[0] for t in db.execute_sql('SELECT name FROM migration').fetchall()}
    if len(current_migrations) == 0:  # Initial table creation, just insert all
        logger.info('Migrations table was just created, inserting all current migrations.')
        _handle_table_creation(db, migrations)
    else:
        logger.debug('Migrations detected, updating state.')
        _handle_migrations(db, migrations, current_migrations)
