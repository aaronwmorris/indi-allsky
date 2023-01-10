#!/usr/bin/env python3

import sys
import argparse
import re
from pathlib import Path
import getpass
from passlib.hash import argon2
#import time
from datetime import datetime
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

    username_regex = r'^[a-zA-Z0-9\@\.\-]+$'
    name_regex = r'^[a-zA-Z0-9_\ \@\.\-]+$'


    def __init__(self):
        pass


    def adduser(self, username=None):

        while True:
            if not username:
                username = input('Username: ')

            if not re.search(self.username_regex, username):
                logger.error('Username contains illegal characters')
                username = None
                continue


            existing_user = IndiAllSkyDbUserTable.query\
                .filter(IndiAllSkyDbUserTable.username == username)\
                .first()

            if existing_user:
                logger.warning('User already exists: %s', username)
                continue


            break


        while True:
            password1 = getpass.getpass('Password (not echoed):')
            password2 = getpass.getpass('Password (again):')

            if password1 != password2:
                logger.error('Password does not match')
                continue

            if len(password1) < 8:
                logger.error('Password must be 8 characters or longer')
                continue

            break


        while True:
            name = input('Name: ')

            if not re.search(self.name_regex, name):
                logger.error('Name contains illegal characters')
                continue

            break


        while True:
            email = input('Email: ')

            if not re.search(self.username_regex, email):
                logger.error('Email contains illegal characters')
                continue

            break


        hashed_password = argon2.hash(password1)
        #logger.info('Hash: %s', hashed_password)

        now = datetime.now()

        user = IndiAllSkyDbUserTable(
            username=username,
            password=hashed_password,
            createDate=now,
            passwordDate=now,
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


        now = datetime.now()

        existing_user.password = hashed_password
        existing_user.passwordDate = now
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

