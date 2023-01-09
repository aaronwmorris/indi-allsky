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


    def adduser(self, username=None):

        if not username:
            username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()

        if existing_user:
            logger.warning('User already exists: %s', username)
            sys.exit(1)

        password1 = getpass.getpass('Password (not echoed):')
        password2 = getpass.getpass('Password (again):')

        if password1 != password2:
            logger.error('Password does not match')
            sys.exit(1)


        name = input('Name: ')
        email = input('Email: ')


        hashed_password = argon2.hash(password1)
        #logger.info('Hash: %s', hashed_password)

        user = IndiAllSkyDbUserTable(
            username=username,
            password=hashed_password,
            name=name,
            email=email,
            active=True,
            staff=True,
            admin=False,
        )

        db.session.add(user)
        db.session.commit()


    def resetpass(self, username=None):

        if not username:
            username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()


        if not existing_user:
            logger.warning('User does not exist: %s', username)
            sys.exit(1)


        password1 = getpass.getpass('Password (not echoed):')
        password2 = getpass.getpass('Password (again):')

        if password1 != password2:
            logger.error('Password does not match')
            sys.exit(1)


        hashed_password = argon2.hash(password1)
        #logger.info('Hash: %s', hashed_password)


        existing_user.password = hashed_password
        db.session.commit()


    def setadmin(self, username=None):

        if not username:
            username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()

        if not existing_user:
            logger.warning('User does not exist: %s', username)
            sys.exit(1)


        existing_user.admin = True
        db.session.commit()


    def removeadmin(self, username=None):

        if not username:
            username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()

        if not existing_user:
            logger.warning('User does not exist: %s', username)
            sys.exit(1)


        existing_user.admin = False
        db.session.commit()



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        type=str,
        choices=(
            'adduser',
            'resetpass',
            'setadmin',
            'removeadmin',
        ),
    )
    argparser.add_argument(
        '--username',
        '-u',
        help='username',
        type=str,
    )


    args = argparser.parse_args()

    um = UserManager()

    action_func = getattr(um, args.action)
    action_func(username=args.username)

