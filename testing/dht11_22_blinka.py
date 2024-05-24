#!/usr/bin/env python3

import board
import adafruit_dht
import logging


IN1 = board.D5
DHT = adafruit_dht.DHT22


logging.basicConfig(level=logging.INFO)
logger = logging


class DhtTempSensor(object):

    def __init__(self):

        self.dht = DHT(IN1, use_pulseio=False)


    def main(self):

        temp_c = self.dht.temperature
        humidity = self.dht.humidity


        logger.info('Temperature device: temp %0.1f, humidity %0.1f%%', temp_c, humidity)


if __name__ == "__main__":
    d = DhtTempSensor()
    d.main()

