"""Retry storage failures only during initialization, before workers start."""
import logging
import time

from sqlalchemy.exc import SQLAlchemyError

from .archive_health import storage_errno


logger = logging.getLogger('indi_allsky')


def retry_storage_start(action, stopped=lambda: False):
    while not stopped():
        try:
            return action()
        except (OSError, SQLAlchemyError) as exc:
            if not storage_errno(exc):
                raise
            logger.warning('Startup is waiting for writable storage (errno %s); retrying in 30s',
                           storage_errno(exc))
        # A SIGTERM/SIGINT handled by the supervisor must still stop promptly.
        for _ in range(30):
            if stopped():
                return None
            time.sleep(1)
    return None
