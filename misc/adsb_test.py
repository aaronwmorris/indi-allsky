#!/usr/bin/env python3

import sys
from pathlib import Path
import logging

import queue
from multiprocessing import Queue
from multiprocessing import Array

from sqlalchemy.orm.exc import NoResultFound

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.adsb import AdsbAircraftHttpWorker


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)



class TestAdsb(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        self.position_av = Array('f', [
            float(self.config['LOCATION_LATITUDE']),
            float(self.config['LOCATION_LONGITUDE']),
            float(self.config.get('LOCATION_ELEVATION', 300)),
            0.0,  # Ra
            0.0,  # Dec
        ])


        self.adsb_worker = None
        self.adsb_worker_idx = 0
        self.adsb_aircraft_q = None


    def main(self):
        if not self.config.get('ADSB', {}).get('ENABLE'):
            logger.warning('ADS-B tracking is disabled')
            sys.exit(1)

        self.adsb_aircraft_q = Queue()
        self.adsb_worker_idx += 1
        self.adsb_worker = AdsbAircraftHttpWorker(
            self.adsb_worker_idx,
            self.config,
            self.adsb_aircraft_q,
            self.position_av[0],  # lat
            self.position_av[1],  # long
            self.position_av[2],  # elev
        )
        self.adsb_worker.start()


        try:
            adsb_aircraft_list = self.adsb_aircraft_q.get(timeout=5.0)
        except queue.Empty:
            adsb_aircraft_list = []

        self.adsb_aircraft_q.close()

        self.adsb_worker.join()


        adsb_aircraft_lines = self.get_adsb_aircraft_text(adsb_aircraft_list)
        for line in adsb_aircraft_lines:
            logger.info(line)


    def get_adsb_aircraft_text(self, adsb_aircraft_list):
        if not self.config.get('ADSB', {}).get('ENABLE'):
            return list()

        if not self.config.get('ADSB', {}).get('LABEL_ENABLE'):
            return list()


        aircraft_lines = []


        for line in self.config.get('ADSB', {}).get('IMAGE_LABEL_TEMPLATE_PREFIX', '').splitlines():
            aircraft_lines.append(line)


        label_limit = self.config.get('ADSB', {}).get('LABEL_LIMIT', 10)
        aircraft_tmpl = self.config.get('ADSB', {}).get('AIRCRAFT_LABEL_TEMPLATE', '')
        for i in range(label_limit):
            try:
                aircraft_data = adsb_aircraft_list[i].copy()
            except IndexError:
                # no more aircraft
                break


            if not aircraft_data['squawk']:
                aircraft_data['squawk'] = ''

            if not aircraft_data['flight']:
                aircraft_data['flight'] = ''

            if not aircraft_data['hex']:
                aircraft_data['hex'] = ''

            try:
                aircraft_data['dir'] = self.cardinal_directions[round(aircraft_data['az'] / 22.5)]
            except IndexError:
                logger.error('Unable to calculate aircraft direction')
                aircraft_data['dir'] = 'Error'


            aircraft_lines.append(aircraft_tmpl.format(**aircraft_data))  # fill in the data


        return aircraft_lines



if __name__ == "__main__":
    TestAdsb().main()

