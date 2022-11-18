#!/usr/bin/env python3

import sys
import argparse
from datetime import datetime
from pathlib import Path
from collections import OrderedDict
import json
import logging

from astropy.io import fits


sys.path.append(str(Path(__file__).parent.absolute().parent))

import indi_allsky

# setup flask context for db access
app = indi_allsky.flask.create_app()
app.app_context().push()

#from indi_allsky.flask import db
#from indi_allsky.flask.models import IndiAllSkyDbBadPixelMapTable
#from indi_allsky.flask.models import IndiAllSkyDbDarkFrameTable


logger = logging.getLogger('indi_allsky')

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)



class ImportDarkFrames(object):

    def __init__(self, f_config_file):
        self.config = self._parseConfig(f_config_file.read())
        f_config_file.close()

        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


    def _parseConfig(self, json_config):
        c = json.loads(json_config, object_pairs_hook=OrderedDict)
        return c


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
        for d in dark_file_list_ordered:
            logger.info('Found fits: %s', d)


            hdulist = fits.open(d)
            #logger.warning('Headers: %s', hdulist[0].header)

            try:
                imagetyp = hdulist[0].header['IMAGETYP']
                logger.info('Detected frame type: %s', imagetyp)
            except KeyError:
                logger.warning('Frame type not marked')


            try:
                instrume = hdulist[0].header['INSTRUME']
                logger.info('Detected camera: %s', instrume)
            except KeyError:
                logger.warning('Camera not logged')
                instrume = None


            try:
                binning = hdulist[0].header['XBINNING']
                logger.info('Detected bin mode: %d', binning)
            except KeyError:
                logger.warning('Bin mode not logged')
                binning = 1


            try:
                gain = hdulist[0].header['GAIN']
                logger.info('Detected gain: %d', gain)
            except KeyError:
                logger.warning('Gain not logged')
                gain = None


            try:
                exptime = hdulist[0].header['EXPTIME']
                logger.info('Detected exposure: %0.1f', exptime)
            except KeyError:
                logger.warning('Exposure not logged')
                exptime = None


            try:
                ccd_temp = hdulist[0].header['CCD-TEMP']
                logger.info('Detected temperature: %0.1f', ccd_temp)
            except KeyError:
                logger.warning('Temperature not logged')
                ccd_temp = None


            try:
                bitpix = hdulist[0].header['BITPIX']
                logger.info('Detected bit depth: %d', bitpix)
            except KeyError:
                logger.warning('Bit depth not logged')
                bitpix = None


            try:
                bayerpat = hdulist[0].header['BAYERPAT']
                logger.info('Detected bayer pattern: %s', bayerpat)
            except KeyError:
                logger.warning('Bayer pattern not logged')
                bayerpat = None


            try:
                date_obs_s = hdulist[0].header['DATE-OBS']
                date_obs = datetime.fromisoformat(date_obs_s)
                logger.info('Detected date: %s', date_obs)
            except KeyError:
                logger.warning('Date not logged')
                date_obs = datetime.utcnow()
            except ValueError:
                logger.warning('Date cannot be parsed')
                date_obs = datetime.utcnow()


            type_options = [
                'Dark Frame',
                'Bad Pixel Map',
                'skip file',
            ]
            file_type = self.select_choice('What type of file is this?', type_options)


    def select_choice(self, question, option_list):
        print('\n{0:s}\n'.format(question))

        for x, option in enumerate(option_list):
            print('{0:d} - {1:s}'.format(x, option))

        i = input('? ')


        try:
            i_int = int(i)
        except ValueError:
            # ask again
            logger.error('Invalid input')
            return self.select_choice(question, option_list)


        try:
            return option_list[i_int]
        except IndexError:
            # ask again
            logger.error('Invalid input')
            return self.select_choice(question, option_list)


    def getFolderFilesByExt(self, folder, file_list, extension_list=[]):
        #logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--config',
        '-c',
        help='config file',
        type=argparse.FileType('r'),
        default='/etc/indi-allsky/config.json',
    )

    args = argparser.parse_args()

    idf = ImportDarkFrames(args.config)
    idf.main()
