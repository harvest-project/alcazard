import json
import logging
import random
import string
import time
import traceback
import urllib.parse
from datetime import datetime
from functools import wraps

from aiohttp import web
from pytz import utc

logger = logging.getLogger(__name__)

DEFAULT_PORT = 7001


def parse_port_pools_fmt(port_pools_fmt):
    def _parse_range(range):
        parts = range.split('-')
        if len(parts) != 2:
            return ValueError('Invalid port range format {}'.format(parts))
        return int(parts[0]), int(parts[1])

    return [_parse_range(range_str) for range_str in port_pools_fmt.split(',')]


def get_ports_from_ranges(port_ranges):
    ports = set()
    for port_range in port_ranges:
        ports.update(range(port_range[0], port_range[1] + 1))
    # Use reverse order so that calling .pop() returns the first available port
    return sorted(ports, reverse=True)


def generate_password(length):
    return ''.join(random.SystemRandom().choice(
        string.ascii_uppercase + string.ascii_lowercase + string.digits) for _ in range(length))


class JsonResponse(web.Response):
    def __init__(self, data, compact=True, **kwargs):
        kwargs.setdefault('content_type', 'application/json')
        indent = None if compact else 4
        super().__init__(text=json.dumps(data, indent=indent), **kwargs)


def timezone_now():
    return datetime.utcnow().replace(tzinfo=utc)


def chunks(iterable, n):
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= n:
            yield chunk
            chunk = []
    if len(chunk):
        yield chunk


def jsonify_exceptions(fn):
    async def inner(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            traceback.print_exc()
            return JsonResponse({
                'detail': str(exc),
                'traceback': traceback.format_exc(),
            }, status=500)

    return inner


_ANNOUNCE_TO_NAME_CACHE = {}


def extract_name_from_announce(announce):
    name = _ANNOUNCE_TO_NAME_CACHE.get(announce)
    if name:
        return name

    try:
        parsed_url = urllib.parse.urlparse(announce)
        name = parsed_url.netloc
    except ValueError:
        name = announce

    _ANNOUNCE_TO_NAME_CACHE[announce] = name
    return name


def set_pop_n(src, n):
    if n >= len(src):
        result = set(src)
        src.clear()
        return result, n - len(result)
    else:
        result = set(src.pop() for _ in range(n))
        return result, 0


def dict_pop_n(src, n):
    if n >= len(src):
        result = dict(src)
        src.clear()
        return result, n - len(result)
    else:
        result = dict(src.popitem() for _ in range(n))
        return result, 0


def log_start_stop_async(fn):
    """For performance debugging purposes."""

    @wraps(fn)
    async def inner(*args, **kwargs):
        start = time.time()
        logger.warning('Start function {}'.format(fn.__name__))
        result = await fn(*args, **kwargs)
        logger.warning('End function {}, took {}'.format(fn.__name__, time.time() - start))
        return result

    return inner
