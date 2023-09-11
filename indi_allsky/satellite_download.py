
import socket
import ssl
import requests
import logging

from .flask import db
from .flask.miscDb import miscDb
from .flask.models import IndiAllSkyDbTleDataTable


logger = logging.getLogger('indi_allsky')


class IndiAllskyUpdateSatelliteData(object):

    # 100 (or so) brightest satellites
    tle_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle'


    def __init__(self, config):
        self.config = config

        self._miscDb = miscDb(self.config)


    def update(self):
        try:
            tle_data = self.download_tle(self.tle_url)
        except socket.gaierror as e:
            logger.error('Name resolution error: %s', str(e))
            return
        except socket.timeout as e:
            logger.error('Timeout error: %s', str(e))
            return
        except requests.exceptions.ConnectTimeout as e:
            logger.error('Connection timeout: %s', str(e))
            return
        except requests.exceptions.ConnectionError as e:
            logger.error('Connection error: %s', str(e))
            return
        except ssl.SSLCertVerificationError as e:
            logger.error('Certificate error: %s', str(e))
            return
        except requests.exceptions.SSLError as e:
            logger.error('Certificate error: %s', str(e))
            return


        # flush entries
        IndiAllSkyDbTleDataTable.query.delete()
        #db.session.commit()


        i = 0

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

            tle_entry = IndiAllSkyDbTleDataTable(
                title=title.rstrip().upper(),
                line1=line1,
                line2=line2,
            )

            db.session.add(tle_entry)
            i += 1


        db.session.commit()
        logger.warning('Updated %d satellites', i)


    def download_tle(self, url):
        logger.warning('Downloading %s', url)
        r = requests.get(url, allow_redirects=True, verify=True, timeout=15.0)

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        return r.text

