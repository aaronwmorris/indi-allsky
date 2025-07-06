#!/usr/bin/env python3

import sys
from pathlib import Path
#import time
from datetime import datetime
import numpy
from astropy.io import fits
import logging

from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound
#from sqlalchemy.exc import IntegrityError


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import create_app
from indi_allsky import constants
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask.miscDb import miscDb

# setup flask context for db access
app = create_app()
app.app_context().push()

#from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbBadPixelMapTable
from indi_allsky.flask.models import IndiAllSkyDbDarkFrameTable


logger = logging.getLogger('indi_allsky')

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)



class ImportDarkFrames(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        self._miscDb = miscDb(self.config)

        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


    def main(self):
        dark_dir = self.image_dir.joinpath('darks')

        logger.info('Searching for files...')

        dark_file_list = list()
        self.getFolderFilesByExt(dark_dir, dark_file_list, extension_list=['fit', 'fits', 'FIT', 'FITS'])

        # Exclude empty files
        dark_file_list_nonzero = filter(lambda p: p.stat().st_size != 0, dark_file_list)

        # Sort by timestamp
        dark_file_list_ordered = sorted(dark_file_list_nonzero, key=lambda p: p.stat().st_mtime)


        logger.info('Found %d dark frame candidates', len(dark_file_list_ordered))


        camera_id = self.select_camera('Which camera is to be used for the dark frames?')
        #logger.info('Selected: %d', camera_id)


        for frame in dark_file_list_ordered:
            print('##########################################')
            logger.info('Found fits: %s', frame)


            # see if file is already imported
            try:
                IndiAllSkyDbDarkFrameTable.query\
                    .filter(
                        or_(
                            IndiAllSkyDbDarkFrameTable.filename == str(frame),
                            IndiAllSkyDbDarkFrameTable.filename == str(frame.relative_to(self.image_dir)),
                        )
                    )\
                    .one()

                logger.warning('File already imported as a dark frame')
                #time.sleep(1.0)
                continue
            except NoResultFound:
                pass


            try:
                IndiAllSkyDbBadPixelMapTable.query\
                    .filter(
                        or_(
                            IndiAllSkyDbBadPixelMapTable.filename == str(frame),
                            IndiAllSkyDbBadPixelMapTable.filename == str(frame.relative_to(self.image_dir)),
                        )
                    )\
                    .one()

                logger.warning('File already imported as a bad pixel map')
                #time.sleep(1.0)
                continue
            except NoResultFound:
                pass


            try:
                hdulist = fits.open(frame)
                #logger.warning('Headers: %s', hdulist[0].header)
            except OSError:
                logger.error('Error decoding fits data: %s', frame)
                continue

            data = dict()

            image_height, image_width = hdulist[0].data.shape[:2]
            data['image_height'] = image_height
            data['image_width'] = image_width

            data['m_avg'] = numpy.mean(hdulist[0].data, axis=0)[0]

            try:
                data['imagetyp'] = hdulist[0].header['IMAGETYP']
                logger.info('Detected frame type: %s', data['imagetyp'])
            except KeyError:
                logger.warning('Frame type not marked')


            try:
                data['instrume'] = hdulist[0].header['INSTRUME']
                logger.info('Detected camera: %s', data['instrume'])
            except KeyError:
                logger.warning('Camera name not logged')


            try:
                data['exptime'] = float(hdulist[0].header['EXPTIME'])
                logger.info('Detected exposure: %0.1f', data['exptime'])
            except KeyError:
                logger.warning('Exposure not logged')
                data['exptime'] = None


            try:
                data['gain'] = int(hdulist[0].header['GAIN'])
                logger.info('Detected gain: %d', data['gain'])
            except KeyError:
                logger.warning('Gain not logged')
                data['gain'] = None


            try:
                data['binning'] = int(hdulist[0].header['XBINNING'])
                logger.info('Detected bin mode: %d', data['binning'])
            except KeyError:
                logger.warning('Bin mode not logged')
                data['binning'] = None


            try:
                data['ccd_temp'] = float(hdulist[0].header['CCD-TEMP'])
                logger.info('Detected temperature: %0.1f', data['ccd_temp'])
            except KeyError:
                logger.warning('Temperature not logged')
                data['ccd_temp'] = None


            try:
                data['bitpix'] = int(hdulist[0].header['BITPIX'])
                logger.info('Detected bit depth: %d', data['bitpix'])
            except KeyError:
                logger.warning('Bit depth not logged')
                data['bitpix'] = None


            try:
                data['bayerpat'] = hdulist[0].header['BAYERPAT']
                logger.info('Detected bayer pattern: %s', data['bayerpat'])
            except KeyError:
                logger.warning('Bayer pattern not logged')
                data['bayerpat'] = None


            try:
                date_obs_s = hdulist[0].header['DATE-OBS']
                data['date_obs'] = datetime.fromisoformat(date_obs_s)
                logger.info('Detected date: %s', data['date_obs'])
            except KeyError:
                logger.warning('Date not logged')
                data['date_obs'] = datetime.fromtimestamp(frame.stat().st_mtime)
            except ValueError:
                logger.warning('Date cannot be parsed')
                data['date_obs'] = datetime.fromtimestamp(frame.stat().st_mtime)


            print('##########################################')
            print('\n\nFile: {0:s}\n'.format(str(frame)))

            frame_options = [
                ['dark', 'Dark Frame'],
                ['bpm', 'Bad Pixel Map'],
                ['skip', 'Skip'],
            ]
            frame_type = self.select_choice('What type of frame?', frame_options)
            #logger.info('Selected: %s', frame_type)


            if frame_type == 'skip':
                continue


            if isinstance(data.get('exptime'), type(None)):
                data['exptime'] = self.select_int('What is the exposure?')
                #logger.info('Selected: %d', data['exptime'])


            if isinstance(data.get('gain'), type(None)):
                data['gain'] = self.select_int('What is the gain?')
                #logger.info('Selected: %d', data['gain'])


            if isinstance(data.get('binning'), type(None)):
                data['binning'] = self.select_int('What is the bin mode?')
                #logger.info('Selected: %d', data['binning'])


            if isinstance(data.get('ccd_temp'), type(None)):
                data['ccd_temp'] = self.select_int('What is the temperature?')
                #logger.info('Selected: %d', data['ccd_temp'])
            else:
                if data['ccd_temp'] <= 0.0:
                    print()
                    temp_over = input('Would you like to override the temperature ({0:0.1f})? [y/n] '.format(data['ccd_temp']))

                    if temp_over.lower() == 'y':
                        data['ccd_temp'] = float(self.select_int('What is the temperature?'))


            if isinstance(data.get('bitpix'), type(None)):
                data['bitpix'] = self.select_int('What is the bit depth?')
                #logger.info('Selected: %d', data['bitpix'])



            print('\n')
            print('Size:        {0:d} x {1:d}'.format(data['image_width'], data['image_height']))
            print('Exposure:    {0:0.1f}'.format(data['exptime']))
            print('Gain:        {0:d}'.format(data['gain']))
            print('Bin mode:    {0:d}'.format(data['binning']))
            print('Temperature: {0:0.1f}'.format(data['ccd_temp']))
            print('Bit depth:   {0:d}'.format(data['bitpix']))
            print('Avg ADU:     {0:0.2f}'.format(data['m_avg']))

            answer_options = [
                [False, 'No'],
                [True, 'Yes'],
            ]
            do_import = self.select_choice('Import frame with the above parameters?', answer_options)

            if not do_import:
                continue

            dark_metadata = {
                'type'       : constants.DARK_FRAME,
                'createDate' : data['date_obs'].timestamp(),
                'bitdepth'   : data['bitpix'],
                'exposure'   : data['exptime'],
                'gain'       : data['gain'],
                'binmode'    : data['binning'],
                'temp'       : data['ccd_temp'],
                'width'      : data['image_width'],
                'height'     : data['image_height'],
                'adu'        : data['m_avg'],
            }

            bpm_metadata = {
                'type'       : constants.BPM_FRAME,
                'createDate' : data['date_obs'].timestamp(),
                'bitdepth'   : data['bitpix'],
                'exposure'   : data['exptime'],
                'gain'       : data['gain'],
                'binmode'    : data['binning'],
                'temp'       : data['ccd_temp'],
                'width'      : data['image_width'],
                'height'     : data['image_height'],
                'adu'        : data['m_avg'],
            }


            # import
            if frame_type == 'bpm':
                self._miscDb.addBadPixelMap(
                    frame,
                    camera_id,
                    dark_metadata,
                )

            elif frame_type == 'dark':
                self._miscDb.addDarkFrame(
                    frame,
                    camera_id,
                    bpm_metadata,
                )

            else:
                raise Exception('This is impossible')




    def select_int(self, question):
        #print('\n{0:s}\n'.format(question))

        i = input('\n{0:s} [int] '.format(question))

        try:
            return int(i)
        except ValueError:
            # ask again
            logger.error('Invalid input')
            return self.select_int(question)



    def select_choice(self, question, option_list):
        print('\n{0:s}\n'.format(question))

        for x, option in enumerate(option_list):
            print('{0:d} - {1:s}'.format(x, option[1]))

        i = input('? [#] ')

        try:
            i_int = int(i)
            return option_list[i_int][0]
        except ValueError:
            # ask again
            logger.error('Invalid input')
            return self.select_choice(question, option_list)
        except IndexError:
            # ask again
            logger.error('Invalid input')
            return self.select_choice(question, option_list)


    def select_camera(self, question):
        camera_query = IndiAllSkyDbCameraTable.query\
            .order_by(IndiAllSkyDbCameraTable.connectDate.asc())

        if camera_query.count() == 0:
            raise Exception('No cameras are recorded in the database')

        camera_options = list()
        for camera in camera_query:
            camera_options.append([camera.id, camera.name])

        return self.select_choice(question, camera_options)


    def getFolderFilesByExt(self, folder, file_list, extension_list=[]):
        #logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion



if __name__ == "__main__":
    idf = ImportDarkFrames()
    idf.main()
