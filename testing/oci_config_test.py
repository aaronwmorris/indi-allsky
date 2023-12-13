#!/usr/bin/env python3

import oci
import sys
from pathlib import Path
import logging
#from pprint import pprint

from sqlalchemy.orm.exc import NoResultFound

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig

# setup flask context for db access
app = create_app()
app.app_context().push()


logging.basicConfig(level=logging.INFO)
logger = logging



class OciConfigTest(object):
    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


    def main(self):

        oci_config = oci.config.from_file(file_location=str(self.config['S3UPLOAD']['CREDS_FILE']))

        oci.config.validate_config(oci_config)

        logger.warning('Test succeeded')


if __name__ == "__main__":
    t = OciConfigTest()
    t.main()
