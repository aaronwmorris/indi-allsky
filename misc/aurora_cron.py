#!/usr/bin/env python3
###########################################
# This script updates the aurora data     #
# for all active cameras in the database  #
# This can be used in remote indi-allsky  #
# installations                           #
###########################################


# Example
# * */3 * * * /home/pi/indi-allsky/misc/aurora_cron.py >/dev/null 2>&1


import sys
from pathlib import Path
import logging


from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import false as sa_false


sys.path.append(str(Path(__file__).parent.absolute().parent))

import indi_allsky
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.aurora import IndiAllskyAuroraUpdate
from indi_allsky.flask.models import IndiAllSkyDbCameraTable

# setup flask context for db access
app = indi_allsky.flask.create_app()
app.app_context().push()



logging.basicConfig(level=logging.INFO)
logger = logging



class AuroraDataUpdater(object):
    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


    def main(self):
        active_cameras = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
            .order_by(IndiAllSkyDbCameraTable.id.desc())


        aurora = IndiAllskyAuroraUpdate(self.config)


        for camera in active_cameras:
            logger.warning('Updating camera: %s', camera.name)
            aurora.update(camera)



if __name__ == "__main__":
    a = AuroraDataUpdater()
    a.main()


