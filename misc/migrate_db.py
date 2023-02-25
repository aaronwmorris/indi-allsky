#!/usr/bin/env python3


import sys
#import argparse
import time
import json
import logging
#import ssl
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.inspection import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

#logging.getLogger('sqlalchemy').setLevel(logging.INFO)


SRC_URL = 'sqlite:////tmp/indi-allsky.sqlite'
DST_URL = 'mysql+mysqlconnector://indi_allsky_own:password123@localhost:3306/indi_allsky?ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_identity'



SRC_ENGINE = create_engine(SRC_URL, echo=False)
src_Base = declarative_base(SRC_ENGINE)

DST_ENGINE = create_engine(DST_URL, echo=False)
dst_Base = declarative_base(DST_ENGINE)


# WAL journal
@event.listens_for(SRC_ENGINE, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    dbapi_connection.execute('PRAGMA journal_mode=WAL')


class MigrateDb(object):

    def __init__(self):
        self.src_session = self._dbConnect(SRC_ENGINE)
        self.dst_session = self._dbConnect(DST_ENGINE)


    def _dbConnect(self, engine):
        Session = sessionmaker(bind=engine)
        return Session()


    def main(self):
        self.migrate_table(src_IndiAllSkyDbCameraTable, dst_IndiAllSkyDbCameraTable)
        self.migrate_table(src_IndiAllSkyDbUserTable, dst_IndiAllSkyDbUserTable)
        self.migrate_table(src_IndiAllSkyDbConfigTable, dst_IndiAllSkyDbConfigTable)  # user foreign keys

        # all tables below have camera foreign keys
        self.migrate_table(src_IndiAllSkyDbImageTable, dst_IndiAllSkyDbImageTable)
        self.migrate_table(src_IndiAllSkyDbDarkFrameTable, dst_IndiAllSkyDbDarkFrameTable)
        self.migrate_table(src_IndiAllSkyDbBadPixelMapTable, dst_IndiAllSkyDbBadPixelMapTable)
        self.migrate_table(src_IndiAllSkyDbVideoTable, dst_IndiAllSkyDbVideoTable)
        self.migrate_table(src_IndiAllSkyDbKeogramTable, dst_IndiAllSkyDbKeogramTable)
        self.migrate_table(src_IndiAllSkyDbStarTrailsTable, dst_IndiAllSkyDbStarTrailsTable)
        self.migrate_table(src_IndiAllSkyDbStarTrailsVideoTable, dst_IndiAllSkyDbStarTrailsVideoTable)
        self.migrate_table(src_IndiAllSkyDbFitsImageTable, dst_IndiAllSkyDbFitsImageTable)
        self.migrate_table(src_IndiAllSkyDbRawImageTable, dst_IndiAllSkyDbRawImageTable)


    def migrate_table(self, src_class, dst_class):
        logger.warning('Processing table %s', str(src_class.__name__))

        table = inspect(src_class)
        column_list = [column.name for column in table.c]

        #logger.warning('Column list: %s', ','.join(column_list))


        src_query = self.src_session.query(src_class)

        dst_entries = list()
        for row in src_query:
            dst_entry = dict()

            for col_name in column_list:
                if col_name == 'data':
                    # columns named data are all json mapped
                    json_data = json.dumps(getattr(row, col_name))
                    dst_entry[col_name] = json_data
                else:
                    col = getattr(row, col_name)
                    dst_entry[col_name] = col

            dst_entries.append(dst_entry)



        start_time = time.time()

        logger.warning('Importing %d rows', len(dst_entries))

        try:
            self.dst_session.bulk_insert_mappings(dst_class, dst_entries)
            self.dst_session.commit()
        except IntegrityError as e:
            logger.error('Integrity error: %s', str(e))
            sys.exit(1)


        elapsed = time.time() - start_time
        logger.warning(' Elapsed: %0.2fs', elapsed)


class src_IndiAllSkyDbCameraTable(src_Base):
    __tablename__ = 'camera'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbImageTable(src_Base):
    __tablename__ = 'image'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbDarkFrameTable(src_Base):
    __tablename__ = 'darkframe'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbBadPixelMapTable(src_Base):
    __tablename__ = 'badpixelmap'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbVideoTable(src_Base):
    __tablename__ = 'video'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbKeogramTable(src_Base):
    __tablename__ = 'keogram'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbStarTrailsTable(src_Base):
    __tablename__ = 'startrail'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbStarTrailsVideoTable(src_Base):
    __tablename__ = 'startrailvideo'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbFitsImageTable(src_Base):
    __tablename__ = 'fitsimage'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbRawImageTable(src_Base):
    __tablename__ = 'rawimage'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbConfigTable(src_Base):
    __tablename__ = 'config'
    __table_args__ = { 'autoload' : True }


class src_IndiAllSkyDbUserTable(src_Base):
    __tablename__ = 'user'
    __table_args__ = { 'autoload' : True }



class dst_IndiAllSkyDbCameraTable(dst_Base):
    __tablename__ = 'camera'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbImageTable(dst_Base):
    __tablename__ = 'image'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbDarkFrameTable(dst_Base):
    __tablename__ = 'darkframe'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbBadPixelMapTable(dst_Base):
    __tablename__ = 'badpixelmap'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbVideoTable(dst_Base):
    __tablename__ = 'video'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbKeogramTable(dst_Base):
    __tablename__ = 'keogram'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbStarTrailsTable(dst_Base):
    __tablename__ = 'startrail'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbStarTrailsVideoTable(dst_Base):
    __tablename__ = 'startrailvideo'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbFitsImageTable(dst_Base):
    __tablename__ = 'fitsimage'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbRawImageTable(dst_Base):
    __tablename__ = 'rawimage'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbConfigTable(dst_Base):
    __tablename__ = 'config'
    __table_args__ = { 'autoload' : True }


class dst_IndiAllSkyDbUserTable(dst_Base):
    __tablename__ = 'user'
    __table_args__ = { 'autoload' : True }



if __name__ == '__main__':
    mdb = MigrateDb().main()

