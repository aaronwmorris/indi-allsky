import time
import traceback
import logging

from threading import Thread
#import queue
import threading

from .devices import dew_heaters
from .devices import temp_sensors
from .devices.exceptions import TemperatureReadException

logger = logging.getLogger('indi_allsky')


class SensorWorker(Thread):
    def __init__(
        self,
        idx,
        config,
        error_q,
        sensors_user_av,
        night_v,
    ):
        super(SensorWorker, self).__init__()

        self.name = 'Sensor-{0:d}'.format(idx)

        self.config = config
        self.error_q = error_q

        self.sensors_user_av = sensors_user_av
        self.night_v = night_v
        self.night = False

        self.dew_heater = None
        self.temp_sensor = None

        self.next_run = time.time()  # run immediately
        self.next_run_offset = 59

        self._stopper = threading.Event()


    def stop(self):
        self._stopper.set()


    def stopped(self):
        return self._stopper.isSet()


    def run(self):
        # setup signal handling after detaching from the main process
        #signal.signal(signal.SIGHUP, self.sighup_handler_worker)
        #signal.signal(signal.SIGTERM, self.sigterm_handler_worker)
        #signal.signal(signal.SIGINT, self.sigint_handler_worker)
        #signal.signal(signal.SIGALRM, self.sigalarm_handler_worker)


        ### use this as a method to log uncaught exceptions
        try:
            self.saferun()
        except Exception as e:
            tb = traceback.format_exc()
            self.error_q.put((str(e), tb))
            raise e


    def saferun(self):
        #raise Exception('Test exception handling in worker')


        self.init_dew_heater()
        self.init_temp_sensor()


        while True:
            time.sleep(3)

            if self.stopped():
                logger.warning('Goodbye')
                return


            now = time.time()
            if not now >= self.next_run:
                continue


            # set next run
            self.next_run = now + self.next_run_offset

            #############################
            ### do interesting stuff here
            #############################


            if self.night != bool(self.night_v.value):
                self.night = bool(self.night_v.value)
                self.night_day_change()


            try:
                temp_data = self.temp_sensor.update()

                with self.sensors_user_av.get_lock():
                    if temp_data['dew_point']:
                        self.sensors_user_av[1] = temp_data['dew_point']

                    if temp_data['frost_point']:
                        self.sensors_user_av[2] = temp_data['frost_point']

                    for i, v in enumerate(temp_data['data']):
                        self.sensors_user_av[self.temp_sensor.slot + i] = float(v)
            except TemperatureReadException as e:
                logger.error('TemperatureReadException: {0:s}'.format(str(e)))


    def night_day_change(self):
        # changing modes here
        if self.night:
            # night time
            if not self.dew_heater.state:
                self.set_dew_heater(self.config.get('DEW_HEATER', {}).get('LEVEL_DEF', 100))

        else:
            # day time
            if self.config.get('DEW_HEATER', {}).get('ENABLE_DAY'):
                if not self.dew_heater.state:
                    self.set_dew_heater(self.config.get('DEW_HEATER', {}).get('LEVEL_DEF', 100))
            else:
                self.set_dew_heater(0)


    def init_dew_heater(self):
        dew_heater_classname = self.config.get('DEW_HEATER', {}).get('CLASSNAME')
        if dew_heater_classname:
            dh = getattr(dew_heaters, dew_heater_classname)
            self.dew_heater = dh(self.config)

            if self.night_v.value:
                self.set_dew_heater(self.config.get('DEW_HEATER', {}).get('LEVEL_DEF', 100))
            else:
                if self.config.get('DEW_HEATER', {}).get('ENABLE_DAY'):
                    self.set_dew_heater(self.config.get('DEW_HEATER', {}).get('LEVEL_DEF', 100))
                else:
                    self.set_dew_heater(0)


        else:
            self.dew_heater = dew_heaters.dew_heater_simulator(self.config)



    def set_dew_heater(self, state):
        self.dew_heater.state = int(state)

        with self.sensors_user_av.get_lock():
            self.sensors_user_av[0] = float(self.dew_heater.state)


    def init_temp_sensor(self):
        temp_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('CLASSNAME')
        if temp_sensor_classname:
            ts = getattr(temp_sensors, temp_sensor_classname)
            self.temp_sensor = ts(self.config)
        else:
            self.temp_sensor = temp_sensors.temp_sensor_simulator(self.config)

        self.temp_sensor.slot = self.config.get('TEMP_SENSOR', {}).get('VAR_SLOT', 10)

