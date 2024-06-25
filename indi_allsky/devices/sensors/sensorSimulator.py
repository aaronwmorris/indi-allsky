# This is a fake device that acts like a temperature sensor but does not actually do anything
import random
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



class SensorDataGenerator(SensorBase):
    def __init__(self, *args, **kwargs):
        super(SensorDataGenerator, self).__init__(*args, **kwargs)

        logger.info('Initializing test data generator sensor')

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

        logger.info('Test Sensor - %d, %0.1f, %d, %d', self.value_1, self.value_2, self.fib_1, rand_value)

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


