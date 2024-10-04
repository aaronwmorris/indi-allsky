
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

        r = requests.get(url, allow_redirects=True, verify=True, timeout=(5.0, 5.0))

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return


        r_data = r.json()

        self.aircraft_q.put(r_data)

