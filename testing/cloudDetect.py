#!/usr/bin/env python3

import sys
from pathlib import Path
import numpy
import cv2
#from PIL import Image
import logging

from keras.models import load_model

from sqlalchemy.orm.exc import NoResultFound

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.flask import db
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig

from indi_allsky.flask.models import IndiAllSkyDbImageTable


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


class CloudDetect(object):
    CLASS_NAMES = (
        '0 Aurora',
        '1 Clear',
        '2 Cloudy',
        '3 AuroraMoon',
        '4 Frost',
        '5 Overcast',
        '6 Snow',
        '7 Partly Cloudy',
    )


    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.model = load_model("keras_model.h5", compile=False)


    def main(self):

        image_entry = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .first()

        image_file = image_entry.getFilesystemPath()

        #with Image.open(str(image_file)) as img:
        #    image = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)

        image = cv2.imread(str(image_file), cv2.IMREAD_UNCHANGED)

        if isinstance(image, type(None)):
            logger.error('Invalid image file: %s', image_file)
            sys.exit(1)


        thumbnail = cv2.resize(image, (224, 224))

        normalized_thumbnail = (thumbnail.astype(numpy.float32) / 127.5) - 1


        data = numpy.ndarray(shape=(1, 224, 224, 3), dtype=numpy.float32)

        data[0] = normalized_thumbnail

        # Predicts the model
        prediction = self.model.predict(data)
        idx = numpy.argmax(prediction)
        class_name = self.CLASS_NAMES[idx]
        confidence_score = prediction[0][idx]

        logger.info('Class: %s', class_name)
        logger.info('Confidence: %s', confidence_score.astype('str'))


if __name__ == "__main__":
    CloudDetect().main()

