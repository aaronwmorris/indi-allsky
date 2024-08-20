
#from datetime import datetime
#from datetime import timedelta
import socket
import ssl
import urllib3.exceptions
import requests
import logging

from . import constants

from .flask import db
from .flask.miscDb import miscDb
from .flask.models import IndiAllSkyDbTleDataTable


logger = logging.getLogger('indi_allsky')


class IndiAllskyUpdateSatelliteData(object):

    tle_urls = {
        constants.SATELLITE_VISUAL    : 'https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle',
        constants.SATELLITE_STARLINK  : 'https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle',
        constants.SATELLITE_STATIONS  : 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle',
    }


    def __init__(self, config):
        self.config = config

        self._miscDb = miscDb(self.config)


    def update(self):
        for group, tle_url in self.tle_urls.items():
            try:
                tle_data = self.download_tle(tle_url)
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                continue
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                continue
            except requests.exceptions.ConnectTimeout as e:
                logger.error('Connection timeout: %s', str(e))
                continue
            except requests.exceptions.ConnectionError as e:
                logger.error('Connection error: %s', str(e))
                continue
            except requests.exceptions.ReadTimeout as e:
                logger.error('Connection error: %s', str(e))
                continue
            except urllib3.exceptions.ReadTimeoutError as e:
                logger.error('Connection error: %s', str(e))
                continue
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                continue
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                continue


            # flush group entries
            IndiAllSkyDbTleDataTable.query\
                .filter(IndiAllSkyDbTleDataTable.group == group)\
                .delete()
            #db.session.commit()


            self.import_entries(group, tle_data)



        # remove old entries
        #now_minus_30d = datetime.now() - timedelta(days=30)
        #IndiAllSkyDbTleDataTable.query\
        #    .filter(IndiAllSkyDbTleDataTable.createDate < now_minus_30d)\
        #    .delete()
        #db.session.commit()


    def import_entries(self, group, tle_data):
        tle_entry_list = list()

        tle_iter = iter(tle_data.splitlines())
        while True:
            try:
                title = next(tle_iter)
            except StopIteration:
                break


            #if line.startswith('#'):
            #    continue
            #elif line == "":
            #    continue


            try:
                line1 = next(tle_iter)
                line2 = next(tle_iter)
            except StopIteration:
                logger.error('Error parsing TLE data')
                db.session.rollback()
                return


            ### https://en.wikipedia.org/wiki/Two-line_element_set
            try:
                assert len(title) <= 24
                assert len(line1) == 69
                assert len(line2) == 69
            except AssertionError:
                logger.error('Error parsing TLE data')
                db.session.rollback()
                return


            #logger.warning('Title: %s %s %s', title, line1, line2)

            tle_entry = {
                'title' : title.strip().upper(),
                'line1' : line1.strip(),
                'line2' : line2.strip(),
                'group' : group,
            }
            tle_entry_list.append(tle_entry)


        db.session.bulk_insert_mappings(IndiAllSkyDbTleDataTable, tle_entry_list)
        db.session.commit()

        logger.warning('Updated %d satellites', len(tle_entry_list))


    def download_tle(self, url):
        logger.warning('Downloading %s', url)
        r = requests.get(url, allow_redirects=True, verify=True, timeout=(15.0, 30.0))

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        return r.text

