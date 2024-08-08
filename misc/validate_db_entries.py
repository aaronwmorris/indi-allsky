#!/usr/bin/env python3

import sys
import time
from pathlib import Path
import logging

from sqlalchemy.sql.expression import true as sa_true
from sqlalchemy.sql.expression import null as sa_null


sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import create_app

# setup flask context for db access
app = create_app()
app.app_context().push()

from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbRawImageTable
from indi_allsky.flask.models import IndiAllSkyDbFitsImageTable
from indi_allsky.flask.models import IndiAllSkyDbBadPixelMapTable
from indi_allsky.flask.models import IndiAllSkyDbDarkFrameTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbMiniVideoTable
from indi_allsky.flask.models import IndiAllSkyDbKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsVideoTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaImageTable
from indi_allsky.flask.models import IndiAllSkyDbPanoramaVideoTable
from indi_allsky.flask.models import IndiAllSkyDbThumbnailTable



logging.basicConfig(level=logging.INFO)
logger = logging


class ValidateDatabaseEntries(object):

    def main(self):
        print()
        print()
        print('This script will verify all of the image and video files in the indi-allsky database')
        print()
        print('Running in 5 seconds... control-c to cancel')
        print()

        time.sleep(5.0)


        ### Images
        image_entries = IndiAllSkyDbImageTable.query\
            .filter(IndiAllSkyDbImageTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbImageTable.createDate.asc())


        logger.info('Searching %d images...', image_entries.count())

        image_notfound_list = list()
        for i in image_entries:
            if not i.validateFile():
                #logger.warning('Entry not found on filesystem: %s', i.filename)
                image_notfound_list.append(i)


        ### FITS Images
        fits_image_entries = IndiAllSkyDbFitsImageTable.query\
            .filter(IndiAllSkyDbFitsImageTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbFitsImageTable.createDate.asc())


        logger.info('Searching %d fits images...', fits_image_entries.count())

        fits_image_notfound_list = list()
        for i in fits_image_entries:
            if not i.validateFile():
                #logger.warning('Entry not found on filesystem: %s', i.filename)
                fits_image_notfound_list.append(i)


        ### Raw Images
        raw_image_entries = IndiAllSkyDbRawImageTable.query\
            .filter(IndiAllSkyDbRawImageTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbRawImageTable.createDate.asc())


        logger.info('Searching %d raw images...', raw_image_entries.count())

        raw_image_notfound_list = list()
        for i in raw_image_entries:
            if not i.validateFile():
                #logger.warning('Entry not found on filesystem: %s', i.filename)
                raw_image_notfound_list.append(i)


        ### Bad Pixel Maps
        badpixelmap_entries = IndiAllSkyDbBadPixelMapTable.query\
            .order_by(IndiAllSkyDbBadPixelMapTable.createDate.asc())
        # fixme - need deal with non-local installs


        logger.info('Searching %d bad pixel maps...', badpixelmap_entries.count())

        badpixelmap_notfound_list = list()
        for b in badpixelmap_entries:
            if not b.validateFile():
                #logger.warning('Entry not found on filesystem: %s', b.filename)
                badpixelmap_notfound_list.append(b)


        ### Dark frames
        darkframe_entries = IndiAllSkyDbDarkFrameTable.query\
            .order_by(IndiAllSkyDbDarkFrameTable.createDate.asc())
        # fixme - need deal with non-local installs


        logger.info('Searching %d dark frames...', darkframe_entries.count())

        darkframe_notfound_list = list()
        for d in darkframe_entries:
            if not d.validateFile():
                #logger.warning('Entry not found on filesystem: %s', d.filename)
                darkframe_notfound_list.append(d)


        ### Videos
        video_entries = IndiAllSkyDbVideoTable.query\
            .filter(IndiAllSkyDbVideoTable.success == sa_true())\
            .filter(IndiAllSkyDbVideoTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbVideoTable.createDate.asc())


        logger.info('Searching %d videos...', video_entries.count())

        video_notfound_list = list()
        for v in video_entries:
            if not v.validateFile():
                #logger.warning('Entry not found on filesystem: %s', v.filename)
                video_notfound_list.append(v)


        ### Mini Videos
        mini_video_entries = IndiAllSkyDbMiniVideoTable.query\
            .filter(IndiAllSkyDbMiniVideoTable.success == sa_true())\
            .filter(IndiAllSkyDbMiniVideoTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbMiniVideoTable.createDate.asc())


        logger.info('Searching %d mini videos...', mini_video_entries.count())

        mini_video_notfound_list = list()
        for m in mini_video_entries:
            if not m.validateFile():
                #logger.warning('Entry not found on filesystem: %s', m.filename)
                mini_video_notfound_list.append(m)


        ### Keograms
        keogram_entries = IndiAllSkyDbKeogramTable.query\
            .filter(IndiAllSkyDbKeogramTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbKeogramTable.createDate.asc())


        logger.info('Searching %d keograms...', keogram_entries.count())

        keogram_notfound_list = list()
        for k in keogram_entries:
            if not k.validateFile():
                #logger.warning('Entry not found on filesystem: %s', k.filename)
                keogram_notfound_list.append(k)


        ### Startrails
        startrail_entries = IndiAllSkyDbStarTrailsTable.query\
            .filter(IndiAllSkyDbStarTrailsTable.success == sa_true())\
            .filter(IndiAllSkyDbStarTrailsTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbStarTrailsTable.createDate.asc())


        logger.info('Searching %d star trails...', startrail_entries.count())

        startrail_notfound_list = list()
        for s in startrail_entries:
            if not s.validateFile():
                #logger.warning('Entry not found on filesystem: %s', s.filename)
                keogram_notfound_list.append(s)



        ### Startrail videos
        startrail_video_entries = IndiAllSkyDbStarTrailsVideoTable.query\
            .filter(IndiAllSkyDbStarTrailsVideoTable.success == sa_true())\
            .filter(IndiAllSkyDbStarTrailsVideoTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbStarTrailsVideoTable.createDate.asc())


        logger.info('Searching %d star trail timelapses...', startrail_video_entries.count())

        startrail_video_notfound_list = list()
        for s in startrail_video_entries:
            if not s.validateFile():
                #logger.warning('Entry not found on filesystem: %s', s.filename)
                startrail_video_notfound_list.append(s)


        ### Panorama Images
        panorama_entries = IndiAllSkyDbPanoramaImageTable.query\
            .filter(IndiAllSkyDbPanoramaImageTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbPanoramaImageTable.createDate.asc())


        logger.info('Searching %d panoramas...', panorama_entries.count())

        panorama_notfound_list = list()
        for p in panorama_entries:
            if not p.validateFile():
                #logger.warning('Entry not found on filesystem: %s', p.filename)
                panorama_notfound_list.append(p)


        ### Panorama videos
        panorama_video_entries = IndiAllSkyDbPanoramaVideoTable.query\
            .filter(IndiAllSkyDbPanoramaVideoTable.success == sa_true())\
            .filter(IndiAllSkyDbPanoramaVideoTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbPanoramaVideoTable.createDate.asc())


        logger.info('Searching %d panorama timelapses...', panorama_video_entries.count())

        panorama_video_notfound_list = list()
        for pv in panorama_video_entries:
            if not pv.validateFile():
                #logger.warning('Entry not found on filesystem: %s', pv.filename)
                panorama_video_notfound_list.append(pv)


        ### Thumbnails
        thumbnail_entries = IndiAllSkyDbThumbnailTable.query\
            .filter(IndiAllSkyDbThumbnailTable.s3_key == sa_null())\
            .order_by(IndiAllSkyDbThumbnailTable.createDate.asc())


        logger.info('Searching %d thumbnail images...', thumbnail_entries.count())

        thumbnail_notfound_list = list()
        for t in thumbnail_entries:
            if not t.validateFile():
                #logger.warning('Entry not found on filesystem: %s', t.filename)
                thumbnail_notfound_list.append(t)



        logger.warning('Images not found: %d', len(image_notfound_list))
        logger.warning('Raw Images not found: %d', len(raw_image_notfound_list))
        logger.warning('FITS Images not found: %d', len(fits_image_notfound_list))
        logger.warning('Bad pixel maps not found: %d', len(badpixelmap_notfound_list))
        logger.warning('Dark frames not found: %d', len(darkframe_notfound_list))
        logger.warning('Videos not found: %d', len(video_notfound_list))
        logger.warning('Mini Videos not found: %d', len(mini_video_notfound_list))
        logger.warning('Keograms not found: %d', len(keogram_notfound_list))
        logger.warning('Star trails not found: %d', len(startrail_notfound_list))
        logger.warning('Star trail videos not found: %d', len(startrail_video_notfound_list))
        logger.warning('Panorama images not found: %d', len(panorama_notfound_list))
        logger.warning('Panorama videos not found: %d', len(panorama_video_notfound_list))
        logger.warning('Thumbnail images not found: %d', len(thumbnail_notfound_list))


        print()
        print()
        ask1 = input('If you agree with the findings above, please approve removing the database entries: (y/n)')
        if ask1.lower() != 'y':
            logger.error('Cancelled')
            sys.exit(1)


        ### DELETE ###
        if len(image_notfound_list):
            logger.warning('Removing %d missing image entries', len(image_notfound_list))
            [db.session.delete(i) for i in image_notfound_list]


        if len(raw_image_notfound_list):
            logger.warning('Removing %d missing raw image entries', len(raw_image_notfound_list))
            [db.session.delete(i) for i in raw_image_notfound_list]


        if len(fits_image_notfound_list):
            logger.warning('Removing %d missing fits image entries', len(fits_image_notfound_list))
            [db.session.delete(i) for i in fits_image_notfound_list]


        if len(badpixelmap_notfound_list):
            logger.warning('Removing %d missing bad pixel map entries', len(badpixelmap_notfound_list))
            [db.session.delete(b) for b in badpixelmap_notfound_list]


        if len(darkframe_notfound_list):
            logger.warning('Removing %d missing dark frame entries', len(darkframe_notfound_list))
            [db.session.delete(d) for d in darkframe_notfound_list]


        if len(video_notfound_list):
            logger.warning('Removing %d missing video entries', len(video_notfound_list))
            [db.session.delete(v) for v in video_notfound_list]


        if len(mini_video_notfound_list):
            logger.warning('Removing %d missing mini video entries', len(mini_video_notfound_list))
            [db.session.delete(m) for m in mini_video_notfound_list]


        if len(keogram_notfound_list):
            logger.warning('Removing %d missing keogram entries', len(keogram_notfound_list))
            [db.session.delete(k) for k in keogram_notfound_list]


        if len(startrail_notfound_list):
            logger.warning('Removing %d missing star trail entries', len(startrail_notfound_list))
            [db.session.delete(s) for s in startrail_notfound_list]


        if len(startrail_video_notfound_list):
            logger.warning('Removing %d missing star trail video entries', len(startrail_video_notfound_list))
            [db.session.delete(s) for s in startrail_video_notfound_list]


        if len(panorama_notfound_list):
            logger.warning('Removing %d missing panorama entries', len(panorama_notfound_list))
            [db.session.delete(p) for p in panorama_notfound_list]


        if len(panorama_video_notfound_list):
            logger.warning('Removing %d missing panorama video entries', len(panorama_video_notfound_list))
            [db.session.delete(pv) for pv in panorama_video_notfound_list]


        if len(thumbnail_notfound_list):
            logger.warning('Removing %d missing thumbnail image entries', len(thumbnail_notfound_list))
            [db.session.delete(t) for t in thumbnail_notfound_list]


        # finalize transaction
        db.session.commit()


if __name__ == "__main__":
    dv = ValidateDatabaseEntries()
    dv.main()
