#!/usr/bin/env python3

import sys
import argparse
from pathlib import Path
import getpass
from passlib.hash import argon2
#import time
#from datetime import datetime
#from datetime import timedelta
import logging

sys.path.append(str(Path(__file__).parent.absolute().parent))

import indi_allsky

# setup flask context for db access
app = indi_allsky.flask.create_app()
app.app_context().push()

from indi_allsky.flask.models import IndiAllSkyDbUserTable

from indi_allsky.flask import db

logging.basicConfig(level=logging.INFO)
logger = logging

#logger.warning('%s', ','.join(sys.path))


class UserManager(object):

    def __init__(self):
        pass


    def add(self):

        username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()

        if existing_user:
            logger.warning('User already exists: %s', username)
            sys.exit(1)

        password = getpass.getpass('Password (not echoed):')

        name = input('Name: ')
        email = input('Email: ')


        hashed_password = argon2.hash(password)
        logger.info('Hash: %s', hashed_password)

        user = IndiAllSkyDbUserTable(
            username=username,
            password=hashed_password,
            name=name,
            email=email,
            active=True,
        )

        db.session.add(user)
        db.session.commit()



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        type=str,
        choices=(
            'add',
        ),
    )

    args = argparser.parse_args()

    um = UserManager()

    action_func = getattr(um, args.action)
    action_func()

