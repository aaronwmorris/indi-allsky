# This is a fake device that acts like a temperature sensor but does not actually do anything
import logging

from .sensorBase import SensorBase


logger = logging.getLogger('indi_allsky')


class SensorSimulator(SensorBase):

    def __init__(self, *args, **kwargs):
        super(SensorSimulator, self).__init__(*args, **kwargs)


    def update(self):
        data = {
            'data' : tuple(),
        }

        return data

