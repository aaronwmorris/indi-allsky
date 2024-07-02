# This is a fake device that acts like a temperature sensor but does not actually do anything
import random
import logging

from .sensorBase import SensorBase
from ... import constants


logger = logging.getLogger('indi_allsky')


class SensorSimulator(SensorBase):

    METADATA = {
        'name' : 'Simulator',
        'description' : 'Simulator',
        'count' : 0,
        'labels' : tuple(),
        'types' : tuple(),
    }


    def __init__(self, *args, **kwargs):
        super(SensorSimulator, self).__init__(*args, **kwargs)


    def update(self):
        data = {
            'data' : tuple(),
        }

        return data



class SensorDataGenerator(SensorBase):

    METADATA = {
        'name' : 'Test Data Generator',
        'description' : 'Test Data Generator',
        'count' : 4,
        'labels' : (
            'Add',
            'Subtract',
            'Fibonacci',
            'Random',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }

    def __init__(self, *args, **kwargs):
        super(SensorDataGenerator, self).__init__(*args, **kwargs)

        logger.info('Initializing [%s] test data generator sensor', self.name)

        self.value_1 = 0
        self.value_2 = 25.0

        # fibonacci
        self.fib_1 = 0
        self.fib_2 = 1


    def update(self):
        self.value_1 += 1
        self.value_2 -= 0.3


        # random
        rand_value = random.randrange(-100, 100, 1)

        logger.info('[%s] Test Sensor - %d, %0.1f, %d, %d', self.name, self.value_1, self.value_2, self.fib_1, rand_value)

        data = {
            'data' : (
                self.value_1,
                self.value_2,
                self.fib_1,
                rand_value,
            ),
        }


        # fibonacci
        self.fib_1, self.fib_2 = self.fib_2, self.fib_1 + self.fib_2
        if self.fib_1 > 2 ** 24:
            # reset values
            self.fib_1 = 0
            self.fib_2 = 1


        return data


