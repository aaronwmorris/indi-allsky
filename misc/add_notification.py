#!/usr/bin/env python3
############################################################
# This script inserts notifications into the indi-allsky   #
# database                                                 #
############################################################

import sys
from pathlib import Path
import argparse
from datetime import timedelta
import logging

from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask.miscDb import miscDb
from indi_allsky.flask.models import NotificationCategory

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



class AddNotification(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        self._miscDb = miscDb(self.config)


    def main(self, category_str, item, message, expire_minutes):
        try:
            category = getattr(NotificationCategory, category_str)
        except AttributeError:
            logger.error('Unknown category')
            sys.exit(1)


        self._miscDb.addNotification(
            category,
            item,
            message,
            expire=timedelta(minutes=expire_minutes),
        )


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'category',
        help='category (GENERAL, MISC, MEDIA, etc)',
        type=str,
    )
    argparser.add_argument(
        'item',
        help='item',
        type=str,
    )
    argparser.add_argument(
        'message',
        help='message',
        type=str,
    )
    argparser.add_argument(
        'expire_minutes',
        help='message expiration (minutes)',
        type=int,
    )


    args = argparser.parse_args()


    AddNotification().main(
        args.category,
        args.item,
        args.message,
        args.expire_minutes,
    )

