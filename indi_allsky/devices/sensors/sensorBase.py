import math


class SensorBase(object):
    def __init__(self, *args, **kwargs):
        self.config = args[0]
        self.name = args[1]
        self.night_v = args[2]

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
        # celcius to fahrenheit
        return (c * 9.0 / 5.0) + 32


    def f2c(self, f):
        # fahrenheit to celcius
        return (f - 32) * 5.0 / 9.0


    def c2k(self, c):
        # celcius to kelvin
        return c + 273.15


    def hPa2psi(self, hpa):
        # hectopascals to pounds/sq in
        return hpa * 0.014503768077999999


    def hPa2inHg(self, hpa):
        # hectopascals to inches mercury
        return hpa * 0.02952998057228486


    def hPa2mmHg(self, hpa):
        # hectopascals to millimeters mercury
        return hpa * 0.7500637554192107


    def mps2kmph(self, mps):
        # meters/sec to kilometers/hour
        return mps * 3.6


    def kmph2miph(self, kmph):
        # kilometers/hour to miles/hour
        return kmph * 0.6213711922


    def mps2miph(self, mps):
        # meters/sec to miles/hour
        return mps * 3.6 * 0.6213711922


    def mm2in(self, mm):
        # millimeters to inches
        return mm * 0.0393700787


    def lux2mag(self, lux):
        # lux to magnitude/arcsec^2
        # http://unihedron.com/projects/darksky/magconv.php
        return math.log10(lux / 108000) / -0.4


    ###
    ### https://github.com/gregnau/heat-index-calc/blob/master/heat-index-calc.py
    ###


    def get_heat_index_f(self, temp_f, rh):
        T2 = pow(temp_f, 2)
        #T3 = pow(temp_f, 3)
        H2 = pow(rh, 2)
        #H3 = pow(rh, 3)


        # Coefficients for the calculations
        C1_f = [ -42.379, 2.04901523, 10.14333127, -0.22475541, -6.83783e-03, -5.481717e-02, 1.22874e-03, 8.5282e-04, -1.99e-06]
        #C2_f = [ 0.363445176, 0.988622465, 4.777114035, -0.114037667, -0.000850208, -0.020716198, 0.000687678, 0.000274954, 0]
        #C3_f = [ 16.923, 0.185212, 5.37941, -0.100254, 0.00941695, 0.00728898, 0.000345372, -0.000814971, 0.0000102102, -0.000038646, 0.0000291583, 0.00000142721, 0.000000197483, -0.0000000218429, 0.000000000843296, -0.0000000000481975]


        heatindex1_f = C1_f[0] + (C1_f[1] * temp_f) + (C1_f[2] * rh) + (C1_f[3] * temp_f * rh) + (C1_f[4] * T2) + (C1_f[5] * H2) + (C1_f[6] * T2 * rh) + (C1_f[7] * temp_f * H2) + (C1_f[8] * T2 * H2)
        #heatindex2_f = C2_f[0] + (C2_f[1] * temp_f) + (C2_f[2] * rh) + (C2_f[3] * temp_f * rh) + (C2_f[4] * T2) + (C2_f[5] * H2) + (C2_f[6] * T2 * rh) + (C2_f[7] * temp_f * H2) + (C2_f[8] * T2 * H2)
        #heatindex3_f = C3_f[0] + (C3_f[1] * temp_f) + (C3_f[2] * rh) + (C3_f[3] * temp_f * rh) + (C3_f[4] * T2) + (C3_f[5] * H2) + (C3_f[6] * T2 * rh) + (C3_f[7] * temp_f * H2) + (C3_f[8] * T2 * H2) + (C3_f[9] * T3) + (C3_f[10] * H3) + (C3_f[11] * T3 * rh) + (C3_f[12] * temp_f * H3) + (C3_f[13] * T3 * H2) + (C3_f[14] * T2 * H3) + (C3_f[15] * T3 * H3)


        return heatindex1_f


    def get_heat_index_c(self, temp_c, rh):
        temp_f = self.c2f(temp_c)

        heat_index_f = self.get_heat_index_f(temp_f, rh)

        return self.f2c(heat_index_f)



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
