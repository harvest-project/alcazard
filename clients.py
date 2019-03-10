import logging
import time
import traceback
from abc import ABC, abstractmethod
from asyncio import CancelledError

from error_manager import ErrorManager, Severity

logger = logging.getLogger(__name__)


class AlcazarException(Exception):
    pass


class TorrentNotFoundException(AlcazarException):
    def __init__(self, message=None, *args, **kwargs):
        message = message or 'Torrent does not exist.'
        super().__init__(message, *args, **kwargs)


class TorrentAlreadyAddedException(AlcazarException):
    def __init__(self, message=None, *args, **kwargs):
        message = message or 'Torrent already added.'
        super().__init__(message, *args, **kwargs)


class FieldInfo:
    def __init__(self, local_name, remote_name, converter=None, public=True):
        self.local_name = local_name
        self.remote_name = remote_name
        self.converter = converter
        self.public = public


class SessionStats:
    def __init__(self):
        self.torrent_count = None
        self.downloaded = None
        self.uploaded = None
        self.download_rate = None
        self.upload_rate = None

    def to_dict(self):
        return dict(self.__dict__)


class TorrentState:
    STATUS_CHECK_WAITING = 0
    STATUS_CHECKING = 1
    STATUS_DOWNLOADING = 2
    STATUS_SEEDING = 3
    STATUS_STOPPED = 4

    STATUS_NAMES = {
        STATUS_CHECK_WAITING: 'check_waiting',
        STATUS_CHECKING: 'checking',
        STATUS_DOWNLOADING: 'downloading',
        STATUS_SEEDING: 'seeding',
        STATUS_STOPPED: 'stopped',
    }

    _FIELD_MAPPING = None

    def __init__(self, manager, info_hash):
        self.manager = manager
        self.info_hash = info_hash

        self.status = None
        self.download_path = None
        self.name = None
        self.size = None
        self.downloaded = None
        self.uploaded = None
        self.download_rate = None
        self.upload_rate = None
        self.progress = None
        self.date_added = None
        self.error = None
        self.tracker_error = None

    def _sync_fields(self, remote):
        updated = False
        for field_info in self._FIELD_MAPPING:
            local_value = getattr(self, field_info.local_name)
            if field_info.remote_name:
                remote_value = getattr(remote, field_info.remote_name)
            else:
                remote_value = remote
            if field_info.converter:
                remote_value = field_info.converter(remote_value)
            if local_value != remote_value:
                setattr(self, field_info.local_name, remote_value)
                updated = True
        return updated

    def to_dict(self):
        result = {field.local_name: getattr(self, field.local_name)
                  for field in self._FIELD_MAPPING
                  if field.public}
        result.update({
            'info_hash': self.info_hash,
            'error': self.error,
            'realm': self.manager.instance_config.realm.name,
            'client': self.manager.name,
        })
        return result


class PeriodicTaskInfo:
    def __init__(self, fn, interval_seconds):
        self.fn = fn
        self.interval_seconds = interval_seconds
        self.last_run_at = None

    async def run_if_needed(self, current_time):
        if not self.last_run_at or current_time - self.last_run_at > self.interval_seconds:
            self.last_run_at = current_time
            await self.fn()
            return True
        return False


class Manager(ABC):
    key = None
    config_model = None

    def __init__(self, orchestrator, instance_config):
        self._orchestrator = orchestrator
        self._config = orchestrator.config
        self._instance_config = instance_config
        # Named used for display/system purposes
        self._name = '{}{:03}'.format(self.key, instance_config.id)
        # Used to track errors, warnings and info messages in the client and the error status.
        self._error_manager = ErrorManager()
        # Set by children when they grab a peer_port
        self._peer_port = None
        # Registry for the periodic tasks
        self._periodic_tasks = []
        # Current instance of SessionStats, as last obtained from the client
        self._session_stats = None

    @property
    def name(self):
        return self._name

    @property
    def config(self):
        return self._config

    @property
    def instance_config(self):
        return self._instance_config

    @property
    def session_stats(self):
        return self._session_stats

    @property
    @abstractmethod
    def peer_port(self):
        pass

    @abstractmethod
    def launch(self):
        pass

    @abstractmethod
    def shutdown(self):
        pass

    @abstractmethod
    def get_info_dict(self):
        return {
            'type': self.key,
            'name': self._name,
            'peer_port': self.peer_port,
            'config': self.instance_config.to_dict(),
            'status': self._error_manager.status,
            'errors': self._error_manager.to_dict(),
            'session_stats': self._session_stats.to_dict() if self._session_stats else None,
        }

    @abstractmethod
    def get_debug_dict(self):
        data = self.get_info_dict()
        data.update({
        })
        return data

    @abstractmethod
    async def add_torrent(self, torrent, download_path):
        pass

    @abstractmethod
    async def delete_torrent(self, info_hash):
        pass

    async def _run_periodic_task_if_needed(self, current_time, task):
        start = time.time()
        ran = await task.run_if_needed(current_time)
        if ran:
            logger.debug('{}.{} took {:.3f}'.format(self._name, task.fn.__name__, time.time() - start))
        return ran

    async def _run_periodic_tasks(self):
        current_time = time.time()
        for task in self._periodic_tasks:
            try:
                ran = await self._run_periodic_task_if_needed(current_time, task)
                if ran:
                    self._error_manager.clear_error(task.fn.__name__)
            except CancelledError:
                return
            except Exception:
                message = 'Periodic task {} running every {}s crashed'.format(
                    task.fn.__name__, task.interval_seconds)
                self._error_manager.add_error(
                    severity=Severity.ERROR,
                    key=task.fn.__name__,
                    message=message,
                    traceback=traceback.format_exc()
                )
                logger.exception(message)


def get_manager_types():
    managers = []

    try:
        from transmission.managed_transmission import ManagedTransmission
        managers.append(ManagedTransmission)
    except (ImportError, ModuleNotFoundError) as exc:
        logger.warning('Unable import managed_transmission: {}.'.format(exc))

    try:
        from transmission.remote_transmission import RemoteTransmission
        managers.append(RemoteTransmission)
    except (ImportError, ModuleNotFoundError) as exc:
        logger.warning('Unable import remote_transmission: {}.'.format(exc))

    try:
        from libtorrent_impl.managed_libtorrent import ManagedLibtorrent
        managers.append(ManagedLibtorrent)
    except (ImportError, ModuleNotFoundError) as exc:
        logger.warning('Unable import managed_libtorrent: {}.'.format(exc))

    return {manager_type.key: manager_type for manager_type in managers}
