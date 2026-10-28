"""SyncAPI scheduling policy; importing this module does not start services."""

import hashlib
from urllib.parse import urlsplit, urlunsplit


def automatic_sync_enabled(config):
    sync = config.get('SYNCAPI', {})
    return bool(sync.get('ENABLE')) and sync.get('MODE', 'automatic') == 'automatic'


def archive_sync_enabled(config):
    sync = config.get('SYNCAPI', {})
    return bool(sync.get('ENABLE')) and sync.get('MODE') == 'archive'


def destination_fingerprint(config):
    """Identify the server/account owning sync IDs, allowing API-key rotation."""
    sync = config.get('SYNCAPI', {})
    url = urlsplit(sync.get('BASEURL', ''))
    if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Set a valid SyncAPI URL without embedded credentials, query, or fragment.')
    port = url.port
    host = url.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    if port and (url.scheme, port) not in (('https', 443), ('http', 80)):
        host += ':' + str(port)
    normalized = urlunsplit((url.scheme.lower(), host, url.path.rstrip('/'), '', ''))
    return hashlib.sha256((normalized + '\n' + sync.get('USERNAME', '')).encode()).hexdigest()


def saved_automatic_sync_enabled(fallback):
    # Read the saved policy as well as the worker snapshot. This closes the gap
    # while capture/upload workers are being restarted after a mode change.
    from .flask.models import IndiAllSkyDbConfigTable
    row = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.createDate.desc()).first()
    return automatic_sync_enabled(row.data if row else fallback)
