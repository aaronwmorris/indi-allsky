import math


class TempSensorBase(object):
    def __init__(self, *args, **kwargs):
        self.config = args[0]

        self._slot = None  # var slot


    def update(self):
        # override in child class
        raise Exception('Not implemented')


    @property
    def slot(self):
        return self._slot

    @slot.setter
    def slot(self, new_slot):
        self._slot = int(new_slot)


    def c2f(self, c):
        return (c * 9.0 / 5.0) + 32

    def f2c(self, f):
        return (f - 32) * 5.0 / 9.0

    def c2k(self, c):
        return c + 273.15

    ###
    ### https://gist.github.com/sourceperl/45587ea99ff123745428
    ###


    def get_frost_point_c(self, t_air_c, dew_point_c):
        """Compute the frost point in degrees Celsius
        :param t_air_c: current ambient temperature in degrees Celsius
        :type t_air_c: float
        :param dew_point_c: current dew point in degrees Celsius
        :type dew_point_c: float
        :return: the frost point in degrees Celsius
        :rtype: float
        """
        dew_point_k = 273.15 + dew_point_c
        t_air_k = 273.15 + t_air_c
        frost_point_k = dew_point_k - t_air_k + 2671.02 / ((2954.61 / t_air_k) + 2.193665 * math.log(t_air_k) - 13.3448)
        return frost_point_k - 273.15


    def get_dew_point_c(self, t_air_c, rel_humidity):
        """Compute the dew point in degrees Celsius
        :param t_air_c: current ambient temperature in degrees Celsius
        :type t_air_c: float
        :param rel_humidity: relative humidity in %
        :type rel_humidity: float
        :return: the dew point in degrees Celsius
        :rtype: float
        """
        A = 17.27
        B = 237.7
        alpha = ((A * t_air_c) / (B + t_air_c)) + math.log(rel_humidity / 100.0)
        return (B * alpha) / (A - alpha)
