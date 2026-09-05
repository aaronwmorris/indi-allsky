#!/usr/bin/env python3

import board
import adafruit_dht
import logging


PIN = board.D5
DHT = adafruit_dht.DHT22
#DHT = adafruit_dht.DHT21
#DHT = adafruit_dht.DHT11


logging.basicConfig(level=logging.INFO)
logger = logging


class DhtTempSensor(object):

    def __init__(self):

        self.dht = DHT(PIN, use_pulseio=False)


    def main(self):

        temp_c = self.dht.temperature
        humidity = self.dht.humidity


        logger.info('Temperature device: temp %0.1f, humidity %0.1f%%', temp_c, humidity)


if __name__ == "__main__":
    d = DhtTempSensor()
    d.main()

