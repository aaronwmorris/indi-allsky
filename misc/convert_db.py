#!/usr/bin/env python3


import sys
#import argparse
import time
import json
import logging
#import ssl
from sqlalchemy import create_engine
from sqlalchemy.schema import Table
from sqlalchemy.schema import MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.inspection import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

#logging.getLogger('sqlalchemy').setLevel(logging.INFO)


SRC_URL = 'sqlite:////var/lib/indi-allsky/indi-allsky.sqlite'

DST_URL = 'mysql+mysqlconnector://indi_allsky_own:password@localhost:3306/indi_allsky?charset=utf8mb4&collation=utf8mb4_unicode_ci'



SRC_ENGINE = create_engine(SRC_URL, echo=False)
SRC_METADATA = MetaData()
SRC_METADATA.reflect(SRC_ENGINE)

DST_ENGINE = create_engine(DST_URL, echo=False)
DST_METADATA = MetaData()
DST_METADATA.reflect(DST_ENGINE)


# WAL journal
@event.listens_for(SRC_ENGINE, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    dbapi_connection.execute('PRAGMA journal_mode=WAL')


class ConvertDb(object):

    def __init__(self):
        self.src_session = self._dbConnect(SRC_ENGINE)
        self.dst_session = self._dbConnect(DST_ENGINE)


    def _dbConnect(self, engine):
        Session = sessionmaker(bind=engine)
        return Session()


    def main(self):
        logger.warning('Migrating in 5 seconds...')
        time.sleep(5.0)

        self.migrate_table(src_IndiAllSkyDbCameraTable, dst_IndiAllSkyDbCameraTable)
        self.migrate_table(src_IndiAllSkyDbUserTable, dst_IndiAllSkyDbUserTable)
        self.migrate_table(src_IndiAllSkyDbConfigTable, dst_IndiAllSkyDbConfigTable)  # user foreign keys

        # all tables below have camera foreign keys
        self.migrate_table(src_IndiAllSkyDbThumbnailTable, dst_IndiAllSkyDbThumbnailTable)
        self.migrate_table(src_IndiAllSkyDbImageTable, dst_IndiAllSkyDbImageTable)
        self.migrate_table(src_IndiAllSkyDbDarkFrameTable, dst_IndiAllSkyDbDarkFrameTable)
        self.migrate_table(src_IndiAllSkyDbBadPixelMapTable, dst_IndiAllSkyDbBadPixelMapTable)
        self.migrate_table(src_IndiAllSkyDbVideoTable, dst_IndiAllSkyDbVideoTable)
        self.migrate_table(src_IndiAllSkyDbKeogramTable, dst_IndiAllSkyDbKeogramTable)
        self.migrate_table(src_IndiAllSkyDbStarTrailsTable, dst_IndiAllSkyDbStarTrailsTable)
        self.migrate_table(src_IndiAllSkyDbStarTrailsVideoTable, dst_IndiAllSkyDbStarTrailsVideoTable)
        self.migrate_table(src_IndiAllSkyDbFitsImageTable, dst_IndiAllSkyDbFitsImageTable)
        self.migrate_table(src_IndiAllSkyDbRawImageTable, dst_IndiAllSkyDbRawImageTable)
        self.migrate_table(src_IndiAllSkyDbPanoramaImageTable, dst_IndiAllSkyDbPanoramaImageTable)
        self.migrate_table(src_IndiAllSkyDbPanoramaVideoTable, dst_IndiAllSkyDbPanoramaVideoTable)


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


#####################
### SOURCE TABLES ###
#####################
class SrcBase(DeclarativeBase):
    pass


class src_IndiAllSkyDbCameraTable(SrcBase):
    __table__ = Table('camera', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbThumbnailTable(SrcBase):
    __table__ = Table('thumbnail', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbImageTable(SrcBase):
    __table__ = Table('image', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbDarkFrameTable(SrcBase):
    __table__ = Table('darkframe', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbBadPixelMapTable(SrcBase):
    __table__ = Table('badpixelmap', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbVideoTable(SrcBase):
    __table__ = Table('video', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbKeogramTable(SrcBase):
    __table__ = Table('keogram', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbStarTrailsTable(SrcBase):
    __table__ = Table('startrail', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbStarTrailsVideoTable(SrcBase):
    __table__ = Table('startrailvideo', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbFitsImageTable(SrcBase):
    __table__ = Table('fitsimage', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbRawImageTable(SrcBase):
    __table__ = Table('rawimage', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbPanoramaImageTable(SrcBase):
    __table__ = Table('panoramaimage', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbPanoramaVideoTable(SrcBase):
    __table__ = Table('panoramavideo', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbConfigTable(SrcBase):
    __table__ = Table('config', SRC_METADATA, autoload_with=SRC_ENGINE)


class src_IndiAllSkyDbUserTable(SrcBase):
    __table__ = Table('user', SRC_METADATA, autoload_with=SRC_ENGINE)


##########################
### DESTINATION TABLES ###
##########################
class DstBase(DeclarativeBase):
    pass


class dst_IndiAllSkyDbCameraTable(DstBase):
    __table__ = Table('camera', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbThumbnailTable(DstBase):
    __table__ = Table('thumbnail', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbImageTable(DstBase):
    __table__ = Table('image', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbDarkFrameTable(DstBase):
    __table__ = Table('darkframe', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbBadPixelMapTable(DstBase):
    __table__ = Table('badpixelmap', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbVideoTable(DstBase):
    __table__ = Table('video', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbKeogramTable(DstBase):
    __table__ = Table('keogram', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbStarTrailsTable(DstBase):
    __table__ = Table('startrail', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbStarTrailsVideoTable(DstBase):
    __table__ = Table('startrailvideo', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbFitsImageTable(DstBase):
    __table__ = Table('fitsimage', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbRawImageTable(DstBase):
    __table__ = Table('rawimage', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbPanoramaImageTable(DstBase):
    __table__ = Table('panoramaimage', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbPanoramaVideoTable(DstBase):
    __table__ = Table('panoramavideo', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbConfigTable(DstBase):
    __table__ = Table('config', DST_METADATA, autoload_with=DST_ENGINE)


class dst_IndiAllSkyDbUserTable(DstBase):
    __table__ = Table('user', DST_METADATA, autoload_with=DST_ENGINE)



if __name__ == '__main__':
    cdb = ConvertDb().main()

