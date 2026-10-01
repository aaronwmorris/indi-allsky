#!/usr/bin/env python3

### Adapted from https://github.com/gordtulloch/mlCloudDetect

import sys
import argparse
from pathlib import Path
import time
from datetime import datetime
from datetime import timedelta
import numpy
import cv2
import PIL
from PIL import Image
import logging

import keras

from sqlalchemy.orm.exc import NoResultFound

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import db
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig

from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable


# setup flask context for db access
app = create_app()


logger = logging.getLogger('indi_allsky')

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


KERAS_MODEL = 'keras_model.h5'


class CloudDetect(object):
    CLASS_NAMES = (
        'Aurora',
        'Clear',
        'Cloudy',
        'AuroraMoon',
        'Frost',
        'Overcast',
        'Snow',
        'Partly Cloudy',
    )


    def __init__(self, camera_id=1):
        self.camera_id = camera_id

        with app.app_context():
            try:
                self._config_obj = IndiAllSkyConfig()
                #logger.info('Loaded config id: %d', self._config_obj.config_id)
            except NoResultFound:
                logger.error('No config file found, please import a config')
                sys.exit(1)

        self.config = self._config_obj.config

        self.exposure_period = self.config.get('EXPOSURE_PERIOD', 15)

        self.model = None


    def main(self):
        logger.warning('Camera %d selected', self.camera_id)

        logger.warning('Using keras model: %s', KERAS_MODEL)
        self.model = keras.models.load_model(KERAS_MODEL)

        while True:
            now_minus_2m = datetime.now() - timedelta(minutes=2)

            with app.app_context():
                latest_image_entry = db.session.query(
                    IndiAllSkyDbImageTable,
                )\
                    .join(IndiAllSkyDbImageTable.camera)\
                    .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
                    .filter(IndiAllSkyDbImageTable.createDate > now_minus_2m)\
                    .order_by(IndiAllSkyDbImageTable.createDate.desc())\
                    .first()

                if not latest_image_entry:
                    logger.warning('No image in 2 minutes')
                    time.sleep(self.exposure_period)
                    continue

                image_file = latest_image_entry.getFilesystemPath()
                logger.warning('Loading image: %s', image_file)


            ### PIL
            try:
                with Image.open(str(image_file)) as img:
                    image_data = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)
            except PIL.UnidentifiedImageError:
                logger.error('Invalid image file: %s', image_file)
                time.sleep(self.exposure_period)
                continue


            ### OpenCV
            #image_data = cv2.imread(str(image_file), cv2.IMREAD_UNCHANGED)

            #if isinstance(image_data, type(None)):
            #    logger.error('Invalid image file: %s', image_file)
            #    time.sleep(self.exposure_period)
            #    continue


            self.detect(image_data)

            time.sleep(self.exposure_period)


    def detect(self, image):
        thumbnail = cv2.resize(image, (224, 224))

        normalized_thumbnail = (thumbnail.astype(numpy.float32) / 127.5) - 1


        data = numpy.ndarray(shape=(1, 224, 224, 3), dtype=numpy.float32)

        data[0] = normalized_thumbnail

        detect_start = time.time()

        # Predicts the model
        prediction = self.model.predict(data)
        idx = numpy.argmax(prediction)
        class_name = self.CLASS_NAMES[idx]
        confidence_score = (prediction[0][idx]).astype(numpy.float32)

        detect_elapsed_s = time.time() - detect_start
        logger.info('Cloud detection in %0.4f s', detect_elapsed_s)


        logger.info('Rating: %s, Confidence %0.3f', class_name, confidence_score)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--Camera',
        '-C',
        help='Camera ID',
        type=int,
        default=1,
    )

    args = argparser.parse_args()


    CloudDetect(camera_id=args.Camera).main()

