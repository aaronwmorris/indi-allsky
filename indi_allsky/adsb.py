import socket
import ssl
import json
import requests
import logging

from threading import Thread

logger = logging.getLogger('indi_allsky')


class AdsbAircraftHttpWorker(Thread):
    def __init__(
        self,
        idx,
        config,
        aircraft_q,
    ):
        super(AdsbAircraftHttpWorker, self).__init__()

        self.name = 'AdsbAircraftHttp-{0:d}'.format(idx)

        self.config = config
        self.aircraft_q = aircraft_q


    def run(self):
        url = self.config.get('ADSB', {}).get('DUMP1090_URL')

        username = self.config.get('ADSB', {}).get('USERNAME')
        password = self.config.get('ADSB', {}).get('PASSWORD')

        cert_bypass = self.config.get('ADSB', {}).get('CERT_BYPASS', True)


        if username:
            basic_auth = requests.HTTPBasicAuth(username, password)
        else:
            basic_auth = None


        if cert_bypass:
            verify = False
        else:
            verify = True


        try:
            r = requests.get(
                url,
                allow_redirects=True,
                verify=verify,
                auth=basic_auth,
                timeout=(5.0, 5.0),
            )
        except socket.gaierror as e:
            logger.error('Socket error: %s', str(e))
            self.aircraft_q.put({})
            return
        except socket.timeout as e:
            logger.error('Socket timeout: %s', str(e))
            self.aircraft_q.put({})
            return
        except requests.exceptions.ConnectTimeout as e:
            logger.error('Connect timeout: %s', str(e))
            self.aircraft_q.put({})
            return
        except requests.exceptions.ConnectionError as e:
            logger.error('Connect error: %s', str(e))
            self.aircraft_q.put({})
            return
        except requests.exceptions.ReadTimeout as e:
            logger.error('Read timeout: %s', str(e))
            self.aircraft_q.put({})
            return
        except ssl.SSLCertVerificationError as e:
            logger.error('SSL Certificate Validation failed: %s', str(e))
            self.aircraft_q.put({})
            return
        except requests.exceptions.SSLError as e:
            logger.error('SSL Error: %s', str(e))
            self.aircraft_q.put({})
            return



        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            self.aircraft_q.put({})
            return


        try:
            r_data = r.json()
        except json.JSONDecodeError as e:
            logger.error('JSON decode error: %s', str(e))
            self.aircraft_q.put({})
            return


        self.aircraft_q.put(r_data)

