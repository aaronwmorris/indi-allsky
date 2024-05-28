from .tempSensorSimulator import TempSensorSimulator as temp_sensor_simulator

from .tempSensorDht import TempSensorDht22 as blinka_temp_sensor_dht22
from .tempSensorDht import TempSensorDht21 as blinka_temp_sensor_dht21
from .tempSensorDht import TempSensorDht11 as blinka_temp_sensor_dht11

from .tempSensorBmp180 import TempSensorBmp180_I2C as blinka_temp_sensor_bmp180_i2c

from .tempSensorBme280 import TempSensorBme280_I2C as blinka_temp_sensor_bme280_i2c
from .tempSensorBme280 import TempSensorBme280_SPI as blinka_temp_sensor_bme280_spi

from .tempSensorBme680 import TempSensorBme680_I2C as blinka_temp_sensor_bme680_i2c
from .tempSensorBme680 import TempSensorBme680_SPI as blinka_temp_sensor_bme680_spi

from .tempSensorSi7021 import TempSensorSi7021_I2C as blinka_temp_sensor_si7021_i2c


__all__ = (
    'temp_sensor_simulator',
    'blinka_temp_sensor_dht22',
    'blinka_temp_sensor_dht21',
    'blinka_temp_sensor_dht11',
    'blinka_temp_sensor_bmp180_i2c',
    'blinka_temp_sensor_bme280_i2c',
    'blinka_temp_sensor_bme280_spi',
    'blinka_temp_sensor_bme680_i2c',
    'blinka_temp_sensor_bme680_spi',
    'blinka_temp_sensor_si7021_i2c',
)
