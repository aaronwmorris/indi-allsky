
import time
from datetime import datetime
from datetime import timedelta
import socket
import ssl
import urllib3.exceptions
import requests
import logging

from sqlalchemy.orm.exc import NoResultFound

from . import constants

from .flask import db
from .flask.miscDb import miscDb
from .flask.models import IndiAllSkyDbTleDataTable
from .flask.models import NotificationCategory


logger = logging.getLogger('indi_allsky')


class IndiAllskyUpdateSatelliteData(object):

    tle_urls = {
        constants.SATELLITE_VISUAL    : 'https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle',
    }

    RATE_LIMIT_BASE_DELAY = 7200       # 2 hours (CelesTrak GP update frequency)
    ERROR_BASE_DELAY = 900             # 15 minutes (network/server errors)
    MAX_BACKOFF_DELAY = 86400          # 24 hours
    FRESHNESS_MIN_INTERVAL = 86400     # 24 hours minimum freshness


    def __init__(self, config):
        self.config = config

        self._miscDb = miscDb(self.config)
        self.last_status_code = None


    def _calculate_backoff(self, is_rate_limit, fail_count):
        base = self.RATE_LIMIT_BASE_DELAY if is_rate_limit else self.ERROR_BASE_DELAY
        return min(base * (2 ** max(0, fail_count - 1)), self.MAX_BACKOFF_DELAY)


    def _record_failure(self, is_rate_limit, error_msg, status_code=None):
        now_time = time.time()
        try:
            fail_count = int(self._miscDb.getState('SATELLITE_TLE_FAIL_COUNT'))
        except (NoResultFound, ValueError, TypeError):
            fail_count = 0

        fail_count += 1
        self._miscDb.setState('SATELLITE_TLE_FAIL_COUNT', fail_count)

        delay = self._calculate_backoff(is_rate_limit, fail_count)
        next_attempt = int(now_time + delay)
        self._miscDb.setState('SATELLITE_TLE_NEXT_ATTEMPT_TS', next_attempt)

        delay_h = delay // 3600
        delay_m = (delay % 3600) // 60
        time_str = f'{delay_h}h' if delay_h > 0 else f'{delay_m}m'

        if is_rate_limit:
            notice_msg = f'CelesTrak TLE rate limit reached (HTTP {status_code}). Backing off for {time_str}.'
        else:
            notice_msg = f'CelesTrak TLE download failed: {error_msg}. Retrying in {time_str}.'

        logger.warning(
            '%s Next attempt at %s (failure count: %d)',
            notice_msg,
            datetime.fromtimestamp(next_attempt).strftime('%Y-%m-%d %H:%M:%S'),
            fail_count,
        )

        try:
            self._miscDb.addNotification(
                NotificationCategory.GENERAL,
                'satellite_tle_error',
                notice_msg,
                expire=timedelta(seconds=delay * 2),
            )
        except Exception as e:
            logger.error('Failed to add satellite TLE notification: %s', str(e))


    def _record_success(self):
        now_time = int(time.time())
        self._miscDb.setState('SATELLITE_TLE_TS', now_time)
        self._miscDb.setState('SATELLITE_TLE_FAIL_COUNT', 0)
        self._miscDb.setState('SATELLITE_TLE_NEXT_ATTEMPT_TS', 0)
        try:
            self._miscDb.clearNotification(NotificationCategory.GENERAL, 'satellite_tle_error')
        except Exception as e:
            logger.debug('Unable to clear satellite TLE notification: %s', str(e))


    def update(self, force=False):
        now_time = time.time()

        if not force:
            # Check if cooldown is active
            try:
                next_attempt = int(self._miscDb.getState('SATELLITE_TLE_NEXT_ATTEMPT_TS'))
            except (NoResultFound, ValueError, TypeError):
                next_attempt = 0

            if next_attempt > now_time:
                remaining = int(next_attempt - now_time)
                rem_h = remaining // 3600
                rem_m = (remaining % 3600) // 60
                time_str = f'{rem_h}h {rem_m}m' if rem_h > 0 else f'{rem_m}m'
                logger.info('Skipping satellite TLE update: cooldown active for %s', time_str)
                return False

            # Check if local data is fresh (< 2 hours old)
            try:
                last_update = int(self._miscDb.getState('SATELLITE_TLE_TS'))
            except (NoResultFound, ValueError, TypeError):
                last_update = 0

            if not last_update:
                latest_entry = IndiAllSkyDbTleDataTable.query\
                    .filter(IndiAllSkyDbTleDataTable.group == constants.SATELLITE_VISUAL)\
                    .order_by(IndiAllSkyDbTleDataTable.createDate.desc())\
                    .first()
                if latest_entry and latest_entry.createDate:
                    last_update = int(latest_entry.createDate.timestamp())
                    self._miscDb.setState('SATELLITE_TLE_TS', last_update)

            if last_update and (now_time - last_update) < self.FRESHNESS_MIN_INTERVAL:
                age_m = int((now_time - last_update) // 60)
                logger.info('Skipping satellite TLE update: cached data is fresh (%d minutes old)', age_m)
                return True

        for group, tle_url in self.tle_urls.items():
            self.last_status_code = None
            tle_data = None
            err_msg = None

            try:
                tle_data = self.download_tle(tle_url)
            except socket.gaierror as e:
                err_msg = f'DNS resolution error: {e}'
            except socket.timeout as e:
                err_msg = f'Socket timeout: {e}'
            except requests.exceptions.ConnectTimeout as e:
                err_msg = f'Connection timeout: {e}'
            except requests.exceptions.ConnectionError as e:
                err_msg = f'Connection error: {e}'
            except requests.exceptions.ReadTimeout as e:
                err_msg = f'Read timeout: {e}'
            except urllib3.exceptions.ReadTimeoutError as e:
                err_msg = f'Read timeout: {e}'
            except (ssl.SSLCertVerificationError, requests.exceptions.SSLError) as e:
                err_msg = f'SSL error: {e}'
            except requests.exceptions.RequestException as e:
                err_msg = f'Request error: {e}'

            if err_msg:
                logger.error('Satellite TLE download error: %s', err_msg)
                self._record_failure(is_rate_limit=False, error_msg=err_msg)
                return False

            if self.last_status_code in (403, 429):
                err_msg = f'Rate limited (HTTP {self.last_status_code})'
                self._record_failure(is_rate_limit=True, error_msg=err_msg, status_code=self.last_status_code)
                return False
            elif self.last_status_code and self.last_status_code >= 400:
                err_msg = f'HTTP error {self.last_status_code}'
                self._record_failure(is_rate_limit=False, error_msg=err_msg, status_code=self.last_status_code)
                return False

            if not tle_data:
                err_msg = 'Empty response received'
                self._record_failure(is_rate_limit=False, error_msg=err_msg)
                return False

            entries = self.parse_tle(group, tle_data)
            if entries is None:
                err_msg = 'Error parsing TLE data'
                self._record_failure(is_rate_limit=False, error_msg=err_msg)
                return False

            # Purge non-visual groups (removes legacy Starlink/Stations)
            IndiAllSkyDbTleDataTable.query\
                .filter(IndiAllSkyDbTleDataTable.group != group)\
                .delete()

            # Flush current group entries
            IndiAllSkyDbTleDataTable.query\
                .filter(IndiAllSkyDbTleDataTable.group == group)\
                .delete()

            if len(entries) > 0:
                db.session.bulk_insert_mappings(IndiAllSkyDbTleDataTable, entries)
                db.session.commit()

            logger.warning('Updated %d satellites', len(entries))

        self._record_success()
        return True


    def parse_tle(self, group, tle_data):
        tle_entry_list = list()

        tle_iter = iter(tle_data.splitlines())
        while True:
            try:
                title = next(tle_iter)
            except StopIteration:
                break

            try:
                line1 = next(tle_iter)
                line2 = next(tle_iter)
            except StopIteration:
                logger.error('Error parsing TLE data')
                return None

            ### https://en.wikipedia.org/wiki/Two-line_element_set
            try:
                assert len(title) <= 24
                assert len(line1) == 69
                assert len(line2) == 69
            except AssertionError:
                logger.error('Error parsing TLE data')
                return None

            tle_entry = {
                'title' : title.strip().upper(),
                'line1' : line1.strip(),
                'line2' : line2.strip(),
                'group' : group,
            }
            tle_entry_list.append(tle_entry)

        return tle_entry_list


    def import_entries(self, group, tle_data):
        tle_entry_list = self.parse_tle(group, tle_data)
        if tle_entry_list is None:
            db.session.rollback()
            return None

        if len(tle_entry_list) > 0:
            db.session.bulk_insert_mappings(IndiAllSkyDbTleDataTable, tle_entry_list)
            db.session.commit()

        logger.warning('Updated %d satellites', len(tle_entry_list))
        return len(tle_entry_list)


    def download_tle(self, url):
        logger.warning('Downloading %s', url)
        r = requests.get(url, allow_redirects=True, verify=True, timeout=(15.0, 30.0))
        self.last_status_code = r.status_code

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        return r.text


