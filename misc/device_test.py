#!/usr/bin/env python3
######################################################
# This script initializes and tests the fan and      #
# dew heater devices.                                #
######################################################


import sys
from pathlib import Path
import argparse
import time
import signal
import logging

from sqlalchemy.orm.exc import NoResultFound


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.devices import generic as indi_allsky_gpios
from indi_allsky.devices import dew_heaters
from indi_allsky.devices import fans
#from indi_allsky.devices.exceptions import DeviceControlException


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


class TestDevices(object):
    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config

        self._sleep = 5

        self.device = None
        self.thold_enable = None
        self.thold_level_low = 0
        self.thold_level_med = 0
        self.thold_level_high = 0

        self._shutdown = False


    @property
    def sleep(self):
        return self._sleep

    @sleep.setter
    def sleep(self, new_sleep):
        #logger.info('Changing image count to %d', int(new_count))
        self._sleep = int(new_sleep)


    def sigint_handler(self, signum, frame):
        logger.warning('Caught INT signal')

        # set flag for program to stop processes
        self._shutdown = True


    def main(self, device_type):
        if device_type == 'dew_heater':
            logger.warning('Testing Dew Heater device')

            dew_heater_classname = self.config.get('DEW_HEATER', {}).get('CLASSNAME')
            if dew_heater_classname:
                dh_class = getattr(dew_heaters, dew_heater_classname)

                dh_i2c_address = self.config.get('DEW_HEATER', {}).get('I2C_ADDRESS', '0x10')
                dh_pin_1 = self.config.get('DEW_HEATER', {}).get('PIN_1', 'notdefined')
                dh_invert_output = self.config.get('DEW_HEATER', {}).get('INVERT_OUTPUT', False)
                dh_pwm_frequency = self.config.get('DEW_HEATER', {}).get('PWM_FREQUENCY', 500)

                self.device = dh_class(
                    self.config,
                    i2c_address=dh_i2c_address,
                    pin_1_name=dh_pin_1,
                    invert_output=dh_invert_output,
                    pwm_frequency=dh_pwm_frequency,
                )

                # set initial state
                self.device.state = 0

                self.thold_enable = self.config.get('DEW_HEATER', {}).get('THOLD_ENABLE')
                self.thold_level_low = self.config.get('DEW_HEATER', {}).get('LEVEL_LOW', 33)
                self.thold_level_med = self.config.get('DEW_HEATER', {}).get('LEVEL_MED', 66)
                self.thold_level_high = self.config.get('DEW_HEATER', {}).get('LEVEL_HIGH', 100)

            else:
                logger.error('Dew Heater not configured')
                sys.exit(1)


        elif device_type == 'fan':
            logger.warning('Testing Fan device')

            fan_classname = self.config.get('FAN', {}).get('CLASSNAME')
            if fan_classname:
                fan_class = getattr(fans, fan_classname)

                fan_i2c_address = self.config.get('FAN', {}).get('I2C_ADDRESS', '0x11')
                fan_pin_1 = self.config.get('FAN', {}).get('PIN_1', 'notdefined')
                fan_invert_output = self.config.get('FAN', {}).get('INVERT_OUTPUT', False)
                fan_pwm_frequency = self.config.get('FAN', {}).get('PWM_FREQUENCY', 500)

                self.device = fan_class(
                    self.config,
                    i2c_address=fan_i2c_address,
                    pin_1_name=fan_pin_1,
                    invert_output=fan_invert_output,
                    pwm_frequency=fan_pwm_frequency,
                )

                # set initial state
                self.device.state = 0

                self.thold_enable = self.config.get('FAN', {}).get('THOLD_ENABLE')
                self.thold_level_low = self.config.get('FAN', {}).get('LEVEL_LOW', 33)
                self.thold_level_med = self.config.get('FAN', {}).get('LEVEL_MED', 66)
                self.thold_level_high = self.config.get('FAN', {}).get('LEVEL_HIGH', 100)

            else:
                logger.error('Fan not configured')
                sys.exit(1)


        elif device_type == 'auto_gpio':
            logger.warning('Testing Automated GPIO device')

            a_gpio__classname = self.config.get('GENERIC_GPIO', {}).get('A_CLASSNAME')
            if a_gpio__classname:
                a_gpio_class = getattr(indi_allsky_gpios, a_gpio__classname)

                a_gpio_i2c_address = self.config.get('GENERIC_GPIO', {}).get('A_I2C_ADDRESS', '0x12')
                a_gpio_pin_1 = self.config.get('GENERIC_GPIO', {}).get('A_PIN_1', 'notdefined')
                a_gpio_invert_output = self.config.get('GENERIC_GPIO', {}).get('A_INVERT_OUTPUT', False)

                self.device = a_gpio_class(
                    self.config,
                    i2c_address=a_gpio_i2c_address,
                    pin_1_name=a_gpio_pin_1,
                    invert_output=a_gpio_invert_output,
                )

                # set initial state
                self.device.state = 0

                self.thold_enable = False  # GPIO has no thresholds

            else:
                logger.error('Auto GPIO not configured')
                sys.exit(1)


        else:
            logger.error('Unknown device type')
            sys.exit(1)


        if self.thold_enable:
            logger.warning('Device thresholds enabled')
        else:
            logger.warning('Device thresholds disabled')


        signal.signal(signal.SIGINT, self.sigint_handler)


        ### Main loop
        while True:
            if self.thold_enable:
                logger.info('Device Level Low')
                self.device.state = self.thold_level_low
                time.sleep(self.sleep)

                self.check_shutdown()


                logger.info('Device Level Medium')
                self.device.state = self.thold_level_med
                time.sleep(self.sleep)

                self.check_shutdown()


                logger.info('Device Level High')
                self.device.state = self.thold_level_high
                time.sleep(self.sleep)

            else:
                logger.info('Device On')
                self.device.state = self.thold_level_high
                time.sleep(self.sleep)


            self.check_shutdown()


            logger.info('Device Off')
            self.device.state = 0
            time.sleep(self.sleep)


            self.check_shutdown()


    def check_shutdown(self):
        if self._shutdown:
            logger.warning('Shutting down')
            self.device.state = 0
            self.device.deinit()
            sys.exit(1)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'device',
        help='action',
        choices=(
            'fan',
            'dew_heater',
            'auto_gpio',
        ),
    )
    argparser.add_argument(
        '--sleep',
        '-s',
        help='sleep time between changes [default: 5]',
        type=int,
        default=5,
    )


    args = argparser.parse_args()


    td = TestDevices()
    td.sleep = 5

    td.main(args.device)

