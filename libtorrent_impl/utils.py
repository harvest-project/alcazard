from utils import extract_name_from_announce


def format_libtorrent_endpoint(endpoint):
    key = 'listen_{}_{}'.format(*endpoint)

    if ':' in endpoint[0]:  # Looks like an IPv6 address
        readable_name = '[{}]:{}'.format(*endpoint)
    else:  # Probably an IPv4 address
        readable_name = '{}:{}'.format(*endpoint)

    return key, readable_name


def format_tracker_error(alert):
    error = alert.error
    return '{}: {} {}: {} - {}'.format(
        extract_name_from_announce(alert.url),
        error.category().name().capitalize(),
        error.value(),
        error.message(),
        alert.msg,
    )


class LibtorrentClientException(Exception):
    pass
