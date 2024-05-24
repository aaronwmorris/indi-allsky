# This is a fake device that acts like a temperature sensor but does not actually do anything
import logging

from .tempSensorBase import TempSensorBase


logger = logging.getLogger('indi_allsky')


class TempSensorSimulator(TempSensorBase):

    def __init__(self, *args, **kwargs):
        super(TempSensorSimulator, self).__init__(*args, **kwargs)


    def update(self):
        data = {
            'dew_point' : None,
            'data' : tuple(),
        }

        return data

