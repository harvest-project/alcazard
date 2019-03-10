import hashlib
import json
import random
import string
import traceback
import urllib.parse
from datetime import datetime
from typing import Set

import bencode
from aiohttp import web
from pytz import utc

DEFAULT_PORT = 7001


def parse_port_pools_fmt(port_pools_fmt):
    def _parse_range(range):
        parts = range.split('-')
        assert len(parts) == 2
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
    chunk = list()
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= n:
            yield chunk
            chunk.clear()
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


class TorrentFileInfo:
    def __init__(self, torrent_data):
        meta_info = bencode.bdecode(torrent_data)
        info = meta_info['info']
        self.name = info['name']
        self.info_hash = hashlib.sha1(bencode.bencode(info)).hexdigest()
        self.files = info.get('files')


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
