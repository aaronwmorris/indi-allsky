#!/usr/bin/env python3
# Multiprocess test for DB concurrency for SQLite in Flask


import time
from datetime import datetime
import string
import random
import signal

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm.exc import NoResultFound
#from sqlalchemy.pool import NullPool

import threading

import logging
from multiprocessing import log_to_stderr


READ_WORKERS  = 10
WRITE_WORKERS = 100


DATABASE_URL = 'sqlite:///test_deleteme.sqlite'  # /// is relative path


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s/%(threadName)s: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)



logger = log_to_stderr()
logger.handlers.clear()
logger.addHandler(LOG_HANDLER_STREAM)
logger.setLevel(logging.WARNING)


db = SQLAlchemy()


class TestTable(db.Model):
    __tablename__ = 'test'

    key = db.Column(db.String(length=32), primary_key=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    value = db.Column(db.String(length=255), nullable=False)



def _sqlite_pragma_on_connect(dbapi_con, con_record):
    dbapi_con.execute('PRAGMA journal_mode=WAL')

    #dbapi_con.execute('PRAGMA synchronous=OFF')
    dbapi_con.execute('PRAGMA synchronous=NORMAL')
    #dbapi_con.execute('PRAGMA synchronous=FULL')

    dbapi_con.execute('PRAGMA busy_timeout=1000')
    #dbapi_con.execute('PRAGMA busy_timeout=10000')


def create_app():
    """Construct the core application."""
    app = Flask(
        __name__,
        instance_relative_config=False,
    )

    app.config['SECRET_KEY'] = 'secretkey'
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "echo"      : False,
        #"poolclass" : NullPool,
    }


    db.init_app(app)
    #migrate.init_app(app, db, directory=foobar)


    with app.app_context():
        from sqlalchemy import event

        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
            event.listen(db.engine, 'connect', _sqlite_pragma_on_connect)

        db.create_all()  # Create sql tables for our data models

        return app



app = create_app()


class BaseWorker(threading.Thread):

    def __init__(self, *args, **kwargs):
        super(BaseWorker, self).__init__(*args, **kwargs)
        self._stopper = threading.Event()


    def stop(self):
        self._stopper.set()


    def stopped(self):
        return self._stopper.isSet()


    def setState(self, key, value):
        now = datetime.now()

        # all keys must be upper-case
        key_upper = str(key).upper()

        # all values must be strings
        value_str = str(value)

        try:
            state = TestTable.query\
                .filter(TestTable.key == key_upper)\
                .one()

            state.value = value_str
            state.createDate = now
        except NoResultFound:
            state = TestTable(
                key=key_upper,
                value=value_str,
                createDate=now,
            )

            db.session.add(state)


        db.session.commit()


    def getState(self, key):
        # all values must be upper-case strings
        key_upper = str(key).upper()

        # not catching NoResultFound
        state = TestTable.query\
            .filter(TestTable.key == key_upper)\
            .one()

        return state.value


    def sigint_handler_worker(self, signum, frame):
        pass


class ReaderWorker(BaseWorker):

    def __init__(self, idx, key):
        super(ReaderWorker, self).__init__()

        self.threadID = idx
        self.name = 'ReaderWorker{0:03d}'.format(idx)

        self.key = key


    def run(self):
        logger.warning('Starting')

        with app.app_context():
            while not self.stopped():
                #random_sleep = random.randrange(100, 300, 10) / 1000
                #time.sleep(random_sleep)
                #time.sleep(0.001)

                start = time.time()

                #self.setState(self.key, int(time.time()))

                try:
                    self.getState(self.key)
                except NoResultFound:
                    pass

                elapsed_s = time.time() - start
                logger.info('Read in %0.4f s', elapsed_s)



class WriterWorker(BaseWorker):

    def __init__(self, idx, key):
        super(WriterWorker, self).__init__()

        self.threadID = idx
        self.name = 'WriterWorker{0:03d}'.format(idx)

        self.key = key


    def run(self):
        logger.warning('Starting')

        with app.app_context():
            while not self.stopped():
                #random_sleep = random.randrange(100, 300, 10) / 1000
                #time.sleep(random_sleep)
                #time.sleep(0.001)

                start = time.time()

                self.setState(self.key, int(time.time()))

                #try:
                #    self.getState(self.key)
                #except NoResultFound:
                #    pass

                elapsed_s = time.time() - start
                logger.info('Write in %0.4f s', elapsed_s)



class SqliteDbTest(object):

    def __init__(self):
        self.shutdown = False

        self.reader_workers = list()
        self.writer_workers = list()

        signal.signal(signal.SIGINT, self.sigint_handler_main)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught SIGINT')
        self.shutdown = True


    def main(self):
        logger.warning('This will cause a lot of disk I/O')
        logger.warning('!!!! DO NOT LEAVE RUNNING FOR LONG PERIODS !!!!')
        logger.warning('Starting in 5 seconds')

        time.sleep(5)

        # create initial data
        key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=25))
        state = TestTable(
            key=key,
            value=str(int(time.time())),
            createDate=datetime.now(),
        )



        logger.warning('Creating key: %s', key)
        with app.app_context():
            db.session.add(state)
            db.session.commit()



        for x in range(READ_WORKERS):
            p = ReaderWorker(x, key)
            self.reader_workers.append(p)
            p.start()


        for x in range(WRITE_WORKERS):
            p = WriterWorker(x, key)
            self.writer_workers.append(p)
            p.start()



        start_time = time.time()


        while True:
            now = time.time()
            if now - start_time > 180:  # 3 minutes
                logger.error('Safety limit reached, terminating')
                self.shutdown = True

            if self.shutdown:
                break

            time.sleep(2)


        for x in self.reader_workers:
            x.stop()
        for x in self.writer_workers:
            x.stop()


        # Wait for the log workers to finish
        for p in self.reader_workers:
            p.join()

        for p in self.writer_workers:
            p.join()


        logger.info('Finished')


if __name__ == "__main__":
    t = SqliteDbTest()
    t.main()

