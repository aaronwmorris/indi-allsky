import time
import statistics
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorException
#from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightningSensorAs3935_SparkFun(SensorBase):
    afemode_outdoor = True
    mask_disturber = False
    noise_level = 2
    watchdog_threshold = 2
    spike_rejection = 2
    lightning_threshold = 1


    def __init__(self, *args, **kwargs):
        super(LightningSensorAs3935_SparkFun, self).__init__(*args, **kwargs)

        self.full_data_list = []
        self.current_data_dict = {
            'distance_list' : [],
            'energy_list' : [],
            'disturber_count' : 0,
            'noise_count' : 0,
        }

        self.full_disturber_count = 0
        self.full_noise_count = 0


    def update(self):
        logger.info('[%s] AS3935 - strikes: %d, disturbers: %d, noise: %d', self.name, len(self.current_data_dict['distance_list']), self.current_data_dict['disturber_count'], self.current_data_dict['noise_count'])


        # present data from the last 5 minutes
        distance_list = []
        disturber_count = 0
        noise_count = 0
        for data in self.full_data_list:
            distance_list += data['distance_list']  # combine lists
            disturber_count += data['disturber_count']
            noise_count += data['noise_count']


        try:
            distance_km_min = min(distance_list)
            distance_km_max = max(distance_list)
        except ValueError:
            distance_km_min = -1
            distance_km_max = -1


        try:
            distance_km_avg = statistics.mean(distance_list)
        except statistics.StatisticsError:
            distance_km_avg = -1.0


        if distance_km_min > -1:
            if self.config.get('TEMP_DISPLAY') == 'f':
                # if using fahrenheit, return in miles
                distance_min = self.km2mi(distance_km_min)
                distance_max = self.km2mi(distance_km_max)
                distance_avg = self.km2mi(distance_km_avg)
            else:
                distance_min = distance_km_min
                distance_max = distance_km_max
                distance_avg = distance_km_avg

        else:
            distance_min = -1
            distance_max = -1
            distance_avg = -1.0


        data = {
            'data' : (
                len(distance_list),
                distance_min,
                distance_max,
                distance_avg,
                disturber_count,
                noise_count,
            ),
        }


        # store current values
        self.full_data_list.append(self.current_data_dict)


        # data is read every 15s, keep last 20 values (5 minutes) for history
        self.full_data_list = self.full_data_list[-20:]


        # new dict for data
        self.current_data_dict = {
            'distance_list' : [],
            'energy_list' : [],
            'disturber_count' : 0,
            'noise_count' : 0,
        }


        return data


    def detection_callback(self, channel):
        ### does this need to be thread safe?
        interrupt_value = self.as3935.read_interrupt_register()

        if interrupt_value == self.as3935.NOISE:
            #logger.info('AS3935 [%s] - Noise detected', self.name)
            self.full_noise_count += 1
            self.current_data_dict['noise_count'] += 1
        elif interrupt_value == self.as3935.DISTURBER:
            #logger.info('AS3935 [%s] - Disturber detected', self.name)
            self.full_disturber_count += 1
            self.current_data_dict['disturber_count'] += 1
        elif interrupt_value == self.as3935.LIGHTNING:
            distance_km = int(self.as3935.distance_to_storm)
            energy = int(self.as3935.lightning_energy)  # energy is meaningless

            logger.info('AS3935 [%s] - Lighting detected - %dkm @ energy %d', self.name, distance_km, energy)

            # not sure if we need a mutex
            self.current_data_dict['distance_list'].append(distance_km)
            self.current_data_dict['energy_list'].append(energy)


    def deinit(self):
        super(LightningSensorAs3935_SparkFun, self).deinit()

        import RPi.GPIO as GPIO

        GPIO.cleanup()


class LightningSensorAs3935_SparkFun_I2C(LightningSensorAs3935_SparkFun):

    METADATA = {
        'name' : 'AS3935 (i2c)',
        'description' : 'AS3935 i2c Lightning Sensor',
        'count' : 6,
        'labels' : (
            'Stike Count',
            'Minimum Distance',
            'Maximum Distance',
            'Average Distance',
            'Disturber Count',
            'Noise Count',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightningSensorAs3935_SparkFun_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']
        # pin1 not used for i2c
        pin_2_name = kwargs['pin_2_name']


        if not pin_2_name:
            raise SensorException('Pin 2 (Interrupt) not defined')


        import board
        #import busio
        import sparkfun_qwiicas3935
        #import signal
        import RPi.GPIO as GPIO

        pin2 = getattr(board, pin_2_name)  # interrupt

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] AS3935 I2C lightning sensor @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.as3935 = sparkfun_qwiicas3935.Sparkfun_QwiicAS3935_I2C(i2c, address=i2c_address)


        time.sleep(1)  # allow things to settle


        if not self.as3935.connected:
            raise SensorException('AS3935 is not connected, check wiring')


        if self.afemode_outdoor:
            self.as3935.indoor_outdoor = self.as3935.OUTDOOR
        else:
            self.as3935.indoor_outdoor = self.as3935.INDOOR

        self.as3935.mask_disturber = self.mask_disturber
        self.as3935.noise_level = self.noise_level
        self.as3935.watchdog_threshold = self.watchdog_threshold
        self.as3935.spike_rejection = self.spike_rejection
        self.as3935.lightning_threshold = self.lightning_threshold


        #GPIO.setmode(GPIO.BOARD)
        GPIO.setmode(GPIO.BCM)

        # rpi.gpio does not use board pins, but we can get the pin number using id
        GPIO.setup(pin2.id, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        GPIO.add_event_detect(
            pin2.id,
            GPIO.RISING,
            callback=self.detection_callback,
            bouncetime=50,
        )

        #signal.signal(signal.SIGINT, signal_handler)
        #signal.pause()


class LightningSensorAs3935_SparkFun_SPI(LightningSensorAs3935_SparkFun):

    METADATA = {
        'name' : 'AS3935 (SPI)',
        'description' : 'AS3935 SPI Ligntning Sensor',
        'count' : 6,
        'labels' : (
            'Strike Count',
            'Minimum Distance',
            'Maximum Distance',
            'Average Distance',
            'Disturber Count',
            'Noise Count',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightningSensorAs3935_SparkFun_SPI, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        pin_2_name = kwargs['pin_2_name']


        if not pin_2_name:
            raise SensorException('Pin 2 (Interrupt) not defined')


        import board
        #import busio
        import digitalio
        import sparkfun_qwiicas3935
        #import signal
        import RPi.GPIO as GPIO

        pin1 = getattr(board, pin_1_name)
        pin2 = getattr(board, pin_2_name)  # interrupt
        cs = digitalio.DigitalInOut(pin1)
        cs.direction = digitalio.Direction.OUTPUT

        logger.warning('Initializing [%s] AS3935 SPI lightning sensor', self.name)
        spi = board.SPI()
        #spi = busio.SPI(board.SCLK, board.MOSI, board.MISO)
        self.as3935 = sparkfun_qwiicas3935.Sparkfun_QwiicAS3935_SPI(spi, cs)


        time.sleep(1)  # allow things to settle


        if not self.as3935.connected:
            raise SensorException('AS3935 is not connected, check wiring')


        if self.afemode_outdoor:
            self.as3935.indoor_outdoor = self.as3935.OUTDOOR
        else:
            self.as3935.indoor_outdoor = self.as3935.INDOOR

        self.as3935.mask_disturber = self.mask_disturber
        self.as3935.noise_level = self.noise_level
        self.as3935.watchdog_threshold = self.watchdog_threshold
        self.as3935.spike_rejection = self.spike_rejection
        self.as3935.lightning_threshold = self.lightning_threshold


        #GPIO.setmode(GPIO.BOARD)
        GPIO.setmode(GPIO.BCM)

        # rpi.gpio does not use board pins, but we can get the pin number using id
        GPIO.setup(pin2.id, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        GPIO.add_event_detect(
            pin2.id,
            GPIO.RISING,
            callback=self.detection_callback,
            bouncetime=50,
        )

        #signal.signal(signal.SIGINT, signal_handler)
        #signal.pause()
