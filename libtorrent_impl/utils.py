import urllib.parse


def format_libtorrent_endpoint(endpoint):
    key = 'listen_{}_{}'.format(*endpoint)

    if ':' in endpoint[0]:  # Looks like an IPv6 address
        readable_name = '[{}]:{}'.format(*endpoint)
    else:  # Probably an IPv4 address
        readable_name = '{}:{}'.format(*endpoint)

    return key, readable_name


def format_tracker_errors(trackers):
    errors = []

    for announce_status in trackers:
        last_error = announce_status['last_error']

        if last_error['value']:
            try:
                parsed_url = urllib.parse.urlparse(announce_status['url'])
                tracker_name = parsed_url.netloc
            except Exception:
                tracker_name = announce_status['url']

            errors.append('{}: {} {}: {}'.format(
                tracker_name,
                last_error['category'].capitalize(),
                last_error['value'],
                announce_status['message'],
            ))

    return '\n'.join(errors) if errors else None


class LibtorrentClientException(Exception):
    pass
