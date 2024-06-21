#!/usr/bin/env python3

import sys
import argparse
import re
from pathlib import Path
import getpass
from passlib.hash import argon2
import secrets
#import time
from datetime import datetime
#from datetime import timedelta
from prettytable import PrettyTable
import logging

from sqlalchemy.exc import IntegrityError

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import create_app

# setup flask context for db access
app = create_app()
app.app_context().push()

from indi_allsky.flask.models import IndiAllSkyDbUserTable

from indi_allsky.flask import db

logging.basicConfig(level=logging.INFO)
logger = logging

#logger.warning('%s', ','.join(sys.path))


class UserManager(object):

    username_regex = r'[\ ]+'  # no spaces
    email_regex = r'^[^@]+@[^@]+\.[^@]+$'

    protected_users = [
        'system',
    ]

    def __init__(self):
        pass


    def list(self, **kwargs):
        table = PrettyTable()
        table.field_names = ['ID', 'Username', 'Full Name', 'Email']


        user_list = IndiAllSkyDbUserTable.query\
            .order_by(IndiAllSkyDbUserTable.createDate.desc())


        for user in user_list:
            table.add_row([user.id, user.username, user.name, user.email])

        print(table)


    def adduser(self, **kwargs):
        username = kwargs.get('username')
        password = kwargs.get('password')
        password2 = kwargs.get('password')
        name = kwargs.get('name')
        email = kwargs.get('email')

        while True:
            if not username:
                username = input('Username: ')

            if re.search(self.username_regex, username):
                logger.error('Username contains illegal characters')
                username = None
                continue


            existing_user = IndiAllSkyDbUserTable.query\
                .filter(IndiAllSkyDbUserTable.username == username)\
                .first()

            if existing_user:
                logger.warning('User already exists: %s', username)
                username = None
                continue

            break


        while True:
            if not password:
                password = getpass.getpass('Password (not echoed):')
                password2 = getpass.getpass('Password (again):')

            if password != password2:
                logger.error('Password does not match')
                password = None
                continue

            if len(password) < 8:
                logger.error('Password must be 8 characters or longer')
                password = None
                continue

            break


        while True:
            if not name:
                name = input('Name: ')

            #if not re.search(self.name_regex, name):
            #    logger.error('Name contains illegal characters')
            #    continue

            break


        while True:
            if not email:
                email = input('Email: ')

            if not re.search(self.email_regex, email):
                logger.error('Email not valid')
                email = None
                continue

            break


        hashed_password = argon2.hash(password)
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


    def deleteuser(self, **kwargs):
        username = kwargs.get('username')

        if not username:
            username = input('Username: ')


        if username in self.protected_users:
            logger.error('%s is protected, unable to delete', username)
            sys.exit(1)


        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()

        if not existing_user:
            logger.warning('User does not exist: %s', username)
            sys.exit(1)


        db.session.delete(existing_user)

        try:
            db.session.commit()
        except IntegrityError as e:
            logger.error('Integrity error: %s', str(e))
            sys.exit(1)


    def resetpass(self, **kwargs):
        username = kwargs.get('username')
        password = kwargs.get('password')
        password2 = kwargs.get('password')

        if not username:
            username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()


        if not existing_user:
            logger.warning('User does not exist: %s', username)
            sys.exit(1)


        if not password:
            password = getpass.getpass('Password (not echoed):')
            password2 = getpass.getpass('Password (again):')


        if password != password2:
            logger.error('Password does not match')
            sys.exit(1)


        hashed_password = argon2.hash(password)
        #logger.info('Hash: %s', hashed_password)


        now = datetime.now()

        existing_user.password = hashed_password
        existing_user.passwordDate = now
        db.session.commit()


    def setadmin(self, **kwargs):
        username = kwargs.get('username')

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


    def removeadmin(self, **kwargs):
        username = kwargs.get('username')

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


    def setactive(self, **kwargs):
        username = kwargs.get('username')

        if not username:
            username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()

        if not existing_user:
            logger.warning('User does not exist: %s', username)
            sys.exit(1)


        existing_user.active = True
        db.session.commit()


    def setinactive(self, **kwargs):
        username = kwargs.get('username')

        if not username:
            username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()

        if not existing_user:
            logger.warning('User does not exist: %s', username)
            sys.exit(1)


        existing_user.active = False
        db.session.commit()


    def genapikey(self, **kwargs):
        username = kwargs.get('username')

        if not username:
            username = input('Username: ')

        existing_user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()

        if not existing_user:
            logger.warning('User does not exist: %s', username)
            sys.exit(1)


        apikey = secrets.token_hex(32)

        # apikeys are encrypted
        existing_user.setApiKey(apikey, app.config['PASSWORD_KEY'])


        print()
        print('API key: {0:s}'.format(apikey))
        print()


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        type=str,
        choices=(
            'list',
            'adduser',
            'deleteuser',
            'resetpass',
            'genapikey',
            'setadmin',
            'removeadmin',
            'setactive',
            'setinactive',
        ),
    )
    argparser.add_argument(
        '--username',
        '-u',
        help='username',
        type=str,
    )
    argparser.add_argument(
        '--password',
        '-p',
        help='password',
        type=str,
        default='',
    )
    argparser.add_argument(
        '--fullname',
        '-f',
        help='full name',
        type=str,
        default='',
    )
    argparser.add_argument(
        '--email',
        '-e',
        help='email',
        type=str,
        default='',
    )


    args = argparser.parse_args()

    um = UserManager()

    action_func = getattr(um, args.action)
    action_func(
        username=args.username,
        password=args.password,
        name=args.fullname,
        email=args.email,
    )

