# Overview
indi-allsky supports reading external sensors (eg temperature) with SBCs like Raspberry Pi.

## Unsupported Hardware
If you have an unsupported sensor, please open an Enhancement Issue and I will investigate adding support.  It may take a week or two if I have to order the part.

## GPIO Permissions
If you receive a `PermissionDenied` exception when accessing GPIO pins

https://github.com/aaronwmorris/indi-allsky/wiki/GPIO-Permissions


## Raspberry Pi 5 - RuntimeError: Cannot determine SOC peripheral base address
```
source virtualenv/indi-allsky/bin/activate

pip uninstall RPi.GPIO rpi.lgpio

pip install --upgrade rpi.lgpio
```

## Sensor Units
Sensor values may be reported in either Celcius or Fahrenheit depending on the setting for `Temperature Display` on the Camera tab under configuration.

## Slots/Probes
Data is shared between the indi-allsky processes using a [multiprocessing Array](https://docs.python.org/3/library/multiprocessing.html#multiprocessing.Array).  **Each sensor module supports a different number of sensor probes.**  Some sensors only support a single probe, others support multiple eg temperature, humidity, pressure, etc.  The code will populate multiple slots of data based on each sensor probe.

**All data from probes are floating point values.**

### System Temperature Slots
There are 60 (0-59) slots for system temperatures.  

* 0 is the camera temperature
* 1-9 are reserved for future use  
* Slots 10-59 are for all sensor values returned by `psutil.sensors_temperatures()`.  Raspberry Pi 1-4 will have a single sensor value (CPU temp), Pi5 has 2 temperatures (CPU Temp, GPU Temp).  Generic PCs can have many temperatures returned.  The order of the temperature values is not controllable, **the first is NOT always the CPU temperature**.  The order and label for the temperatures can be seen on the System page.   

#### System Temp Slot Overlay variables
```
{sensor_temp_1:0.1f}
{sensor_temp_2:0.1f}
{sensor_temp_3:0.1f}
{sensor_temp_4:0.1f}
{sensor_temp_5:0.1f}
{sensor_temp_6:0.1f}
{sensor_temp_7:0.1f}
{sensor_temp_8:0.1f}
{sensor_temp_9:0.1f}
{sensor_temp_10:0.1f}
...
{sensor_temp_59:0.1f}
```


### User Slots
There are 60 (0-59) sensor slots for user data.

* 0 is the camera temperature
* 1 is the dew heater state (duty cycle)
* 2 is the dew point temperature
* 3 is the frost point temperature
* 4 is the fan state (duty cycle)
* 5 is the heat index
* 6 is the wind direction in degrees
* 7 is device sqm magnitude
* 8 is camera sqm magnitude
* 9 is camera sqm adu
* Slots 10-59 are available to be assigned for sensors.

#### User Slot Overlay variables
```
{sensor_user_1:0.1f}
{sensor_user_2:0.1f}
{sensor_user_3:0.1f}
{sensor_user_4:0.1f}
{sensor_user_5:0.1f}
{sensor_user_6:0.1f}
{sensor_user_7:0.1f}
{sensor_user_8:0.1f}
{sensor_user_9:0.1f}
{sensor_user_10:0.1f}
...
{sensor_user_59:0.1f}
```

## Chart Titles
Chart titles may be customized by updating the title template

Default: `{name:s} - {label:s} - {probe:s}`

### Title Variables

| Name           | Type         | Info |
| -------------- | ------------ | ---- |
| name           | str          | Sensor Name |
| title          | str          | Sensor Title |
| probe          | str          | Probe Name |


## Testing sensors
There is a test script will will execute the same code that indi-allsky utilizes so you do not have to start the program to validate their behavior.

```
source virtualenv/indi-allsky/bin/activate

./misc/sensor_test.py
```

## Interfaces
### I2C
The I2C interface may be activated with `sudo raspi-config` on Raspberry Pi systems.  `sudo armbian-config` on Armbian.

Use `i2cdetect -y 1` to inspect the I2C bus to find the correct address for your device.

#### i2c extended detection
Use the following command to scan the lower 7 addresses.
`i2cdetect -a -y 1 0x00 0x77`

```
sudo apt-get install i2c-tools
```

#### Alternate I2C buses
On a Raspberry Pi, most people would use I2C bus 1 (pins 2/3).  However, there are cases where it is necessary to use I2C bus 0 (pins 27/28) if a HAT is using those pins.  The code will have to be manually updated to use the alternate bus.

* /etc/firmware/config.txt

        dtparam=i2c_vc=on

* Sensor modifications
```diff
         i2c_address_str = kwargs['i2c_address']
 
         import board
-        #import busio
+        import busio
         import adafruit_bh1750
 
         i2c_address = int(i2c_address_str, 16)  # string in config
 
         logger.warning('Initializing [%s] BH1750 I2C light sensor device @ %s', self.name, hex(i2c_address))
-        i2c = board.I2C()
+        #i2c = board.I2C()
+        i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
         self.bh1750 = adafruit_bh1750.BH1750(i2c, address=i2c_address)
```

### SPI
The SPI interface may be activated with `sudo raspi-config` on Raspberry Pi systems.


### 1-Wire
The 1-Wire interface may be activated with `sudo raspi-config` on Raspberry Pi systems.

The default 1-Wire pin on Raspberry Pi devices is GPIO4 (pin 7).  This can be overridden in `/boot/firmware/config.txt`

```
dtoverlay=w1-gpio,gpiopin=5
```

Note:  The pin designated as 1-Wire cannot be used as a GPIO pin while this overlay is active.

## Sensors
| Sensor   | Type  | Status |
| -------- | ----- | ------ |
| OpenWeather Map API | Temp | Working |
| Weather Underground API | Temp | Working |
| Astrospheric API | Temp | Working |
| Ambient Weather API | Temp | Working |
| Ecowitt API | Temp | Working |
| MQTT Broker |    | Working |
| DS18x20  | Temp  | Working |
| DHT11    | Temp  | Working |
| DHT21    | Temp  | My sample did not work |
| DHT22    | Temp  | Working |
| SHT20    | Temp  | Select `HTU21D` interface |
| SHT3x    | Temp  | Working - Heater untested |
| SHT4x    | Temp  | Working - Heater untested |
| HTU21D   | Temp  | Working |
| HTU31D   | Temp  | Not tested - Heater untested |
| AHT10/20 | Temp  | Working |
| BMP180   | Temp  | Working |
| BMP280   | Temp  | Working - BMP do not report humidity |
| BME280   | Temp  | Working |
| BME680   | Temp  | Working |
| BMP3xx   | Temp  | Untested |
| Si7021   | Temp  | Working - Heater untested |
| SCD-30   | Temp  | Untested |
| SCD-4x   | Temp  | Untested |
| HDC302x  | Temp  | Untested |
| MLX90614 | Sky Temp | Working |
| MLX90615 | Sky Temp | Working |
| MLX90640 | Thermal Camera | Working |
| TMP36 via ADS1015  | Temp | Working |
| TMP36 via ADS1115  | Temp | Untested |
| LM35 via ADS1015   | Temp | Untested |
| LM35 via ADS1115   | Temp | Untested |
| TSL2561  | Light | Working |
| TSL2591  | Light | Working |
| VEML7700 | Light | Working |
| BH1750   | Light | Working |
| SI1145   | Light | Working |
| LTR390   | Light | Working |
| MMC5983MA | Magnet | Working |
| INA219   | Current | Working |
| INA228   | Current | Working |
| INA23x   | Current | Untested |
| INA260   | Current | Untested |
| INA3221  | Current | Untested |
| SGP40    | VOC Air Quality | Untested |
| ICM20x   | IMU | Untested |
| MPU6050  | IMU | Working |
| AS3935   | Lightning | Working (beta) |


### OpenWeather Map ###
The OpenWeather Map API may be used to query local weather conditions for your location.  This is not a physical sensor, but data is returned for your local weather conditions based on longitude and latitude.

https://openweathermap.org/api

The API is queried every 5 minutes, therefore there should be no more than 288 (automated) queries per day.

Returns 10 values:
* `temperature`
* `"Feels Like" temperature`
* `humidity`
* `pressure`
* `clouds percent`
* `wind speed`
* `wind gusts`
* `1h rain`
* `1h snow`
* `dew point`

Additional values:
* `dew point`
* `frost point`
* `heat index`
* `wind direction`

### Weather Underground ###
The Weather Underground API may be used to query weather conditions.  This is not a physical sensor, but data is returned for your local weather conditions based on a given Station ID.

https://www.wunderground.com/

The API is queried every 5 minutes, therefore there should be no more than 288 (automated) queries per day.

Note: **The `Pin/Port` field is used for the `Station ID`**

Returns 9 values:
* `temperature`
* `humidity`
* `pressure`
* `wind speed`
* `wind gusts`
* `total rain`
* `solar radiation`
* `uv`
* `dew point`

Additional values:
* `dew point`
* `frost point`
* `heat index`
* `wind direction`

### Astrospheric ###
The Astrospheric API may be used to query weather conditions.  This is not a physical sensor, but data is returned for your local weather conditions based on a given Latitude/Longitude.

https://www.astrospheric.com/

The API is queried every 120 minutes, therefore there should be no more than 12 (automated) queries per day.

_Note: As of January 2025, users are granted 100 API credits per day and each call to the API incurs a cost of 5 credits._

Returns 6 values:
* `temperature`
* `atmospheric seeing`
* `atmospheric transparency`
* `clouds percent`
* `wind speed`
* `dew point`

Additional values:
* `dew point`
* `frost point`
* `wind direction`


### Ambient Weather ###
The Ambient Weather API may be used to query weather conditions provided by your local weather device.  This is not a physical sensor, but data is returned for your local weather conditions provided by your Ambient Weather internet connected device.

https://www.ambientweather.net/

API Key Instruction:  https://ambientweather.com/faqs/question/view/id/1834/

The API is queried every 5 minutes.

Returns 10 values:
* `temperature`
* `feels like seeing`
* `relative humidity`
* `atmospheric pressure`
* `wind speed`
* `wind gust speed`
* `1hr rain`
* `solar radiation`
* `uv`
* `dew point`

Additional values:
* `dew point`
* `frost point`
* `heat index`
* `wind direction`

Ambient Weather requires three values to access their API:
* API Key - Obtained from your ambientweather.net Dashboard, Account, then API Keys. Create a new API Key or re-use an existing one.
* Application Key - Obtained from the same page as the API Key. Create an Application key by clicking the Developers `Click here` link. You're asked to describe the application that you are developing. Indicate that you'll be using the API to get data for a personal All Sky camera.
* Device MAC Address - Obtained from the Devices page.

NOTE: Not all values will populate with data. Values will only be populated for the data sent by your weather station.

### Ecowitt ###
The Ecowitt API may be used to query weather conditions provided by your local weather device.  This is not a physical sensor, but data is returned for your local weather conditions provided by your Ecowitt internet connected device.

https://www.ecowitt.net/

The API is queried every 5 minutes.

Returns 10 values:
* `temperature`
* `feels like seeing`
* `relative humidity`
* `atmospheric pressure`
* `wind speed`
* `wind gust speed`
* `1hr rain`
* `solar radiation`
* `uv`
* `dew point`

Additional values:
* `dew point`
* `frost point`
* `heat index`
* `wind direction`

Ecowitt requires three values to access their API:
* API Key - Obtained from your ecowitt.net Dashboard. Click your account icon then User Profile Create a new API Key or re-use an existing one.
* Application Key - Obtained from the same page as the API Key. You're asked to describe the application that you are developing. Indicate that you'll be using the API to get data for a personal All Sky camera.
* Device MAC Address - Obtained from the Devices page (unconfirmed).


### MQTT Broker Sensor ###
A sensor value from an MQTT Broker may be queried.  The `Pin` field is used for the topic subscription.  Up to 10 topics may be subscribed by providing a comma separated list.  eg `topic1,base/topic2`

The payload for the topics must be a value that can be converted to a float.

A sensor value from an MQTT Broker may be queried. The Pin field is used for the topic subscription. Up to 10 topics may be subscribed to by providing a comma-separated list (e.g., topic1, base/topic2).

The payload for the topics must be a value that can be converted to a float.

By default, the labels for the charts and overlays (Topic 1, Topic 2, etc.) are statically defined within the sensor code. If you want to hardcode these names, the METADATA code will have to be changed ([mqttBrokerSensor.py](https://github.com/aaronwmorris/indi-allsky/blob/main/indi_allsky/devices/sensors/mqttBrokerSensor.py)).

#### Dynamic Labels ####
Alternatively, the sensor will now automatically attempt to derive human-readable labels directly from your configured topic names:

Standard topics will extract the final element of the path (e.g., weather/roof/wind_speed automatically becomes Wind Speed).

Convention paths like ESPHome or Home Assistant (ending in /state) will extract the preceding sensor name (e.g., esphome/sensor/outside_temp/state becomes Outside Temp).

Unparseable topics or unfilled slots will gracefully fall back to the static Topic N format.

Returns 10 float values


### DS18x20 Dallas Temperature Sensor
This sensor is a 1-Wire interface type device.  On Raspberry Pi, the default 1-Wire pin is GPIO4 (pin 7).  The Pin in the indi-allsky config is not used.

Returns 1 value:
* `temperature`


### DHT11/21/22 Temperature Sensor
This sensor only requires a single pin and in some cases a pull up resistor.

Returns 3 values:
* `temperature`
* `humidity`
* `dew point`

### BMP180 Temperature Sensor
The BMP180 has an i2c interface.  Common I2C addresses are `0x77` and `0x76`.

Returns 2 values:
* `temperature`
* `pressure`

| Pin | I2C  | Note |
| --- | ---- | ---- |
| VCC |      | 5v on 5 pin sensors, 3.3v on 4 pin modules |
| GND |      |      |
| SLC | SLC  | Raspi pin 5 (GPIO 3) |
| SDA | SDA  | Raspi pin 3 (GPIO 2) |
| 3.3 |      | Not available on 4 pin modules |

### BMP280 Temperature Sensor
The BME280 can be used in either i2c or SPI modes.  Common I2C addresses are `0x77` and `0x76`.

BMP280 does not support humidity measurements.  **Without the humidity measurement, dew point calculations will not be available.**

Returns 2 values:
* `temperature`
* `pressure`

| Pin | I2C  | SPI  | Note |
| --- | ---- | ---- | ---- |
| VCC |      |      | Usually 3.3v |
| GND |      |      |      |
| SLC | SLC  | SCLK | I2C - Raspi pin 5 (GPIO 3)<br>SPI - Raspi pin 23 (SCLK) (GPIO 11) |
| SDA | SDA  | MISO | I2C - Raspi pin 3 (GPIO 2)<br>SPI - Raspi pin 19 (MOSI) (GPIO 10) |
| CSB |      | CS   | SPI - Any GPIO pin |
| SDO |      | MOSI | SPI - Raspi pin 21 (MISO) (GPIO 9) |


### BME280 Temperature Sensor
The BME280 can be used in either i2c or SPI modes.  Common I2C addresses are `0x77` and `0x76`.

Returns 4 values:
* `temperature`
* `humidity`
* `pressure`
* `dew point`

| Pin | I2C  | SPI  | Note |
| --- | ---- | ---- | ---- |
| VCC |      |      | Usually 3.3v |
| GND |      |      |      |
| SLC | SLC  | SCLK | I2C - Raspi pin 5 (GPIO 3)<br>SPI - Raspi pin 23 (SCLK) (GPIO 11) |
| SDA | SDA  | MISO | I2C - Raspi pin 3 (GPIO 2)<br>SPI - Raspi pin 19 (MOSI) (GPIO 10) |
| CSB |      | CS   | SPI - Any GPIO pin |
| SDO |      | MOSI | SPI - Raspi pin 21 (MISO) (GPIO 9) |

#### Chip ID 0x58

```
RuntimeError: Failed to find BME280! Chip ID 0x58
```

If you receive this Exception, you have a `BMP280` module (not BME).  You should use the separate BMP280 support, but if you need to use the BME280 module, edit `virtualenv/indi-allsky/lib/python3.##/site-packages/adafruit_bme280/basic.py` and set `_BME280_CHIPID` to `0x58`

### BME680 Temperature Sensor
The BME680 can be used in either i2c or SPI modes.  Common I2C addresses are `0x77` and `0x76`.

Returns 5 values:
* `temperature`
* `humidity`
* `pressure`
* `gas` (ohm)
* `dew point`

| Pin | I2C  | SPI  | Note |
| --- | ---- | ---- | ---- |
| VCC |      |      | Usually 3.3v |
| GND |      |      |      |
| SLC | SLC  | SCLK | I2C - Raspi pin 5 (GPIO 3)<br>SPI - Raspi pin 23 (SCLK) (GPIO 11)|
| SDA | SDA  | MISO | I2C - Raspi pin 3 (GPIO 2)<br>SPI - Raspi pin 19 (MOSI) (GPIO 10)|
| SDO |      | MOSI | SPI - Raspi pin 21 (MISO) (GPIO 9)|
| CSB |      | CS   | SPI - Any GPIO pin |

#### BME680 notes
* The initial humidity measurement may always be 100%.  Subsequent measurements should be correct.


### BMP3xx Temperature Sensor
The BMP3xx can be used in either i2c or SPI modes.  Default I2C addresses is `0x77`.

Returns 3 values:
* `temperature`
* `humidity`
* `dew point`


### Si7021 Temperature Sensor
The Si7021 has an i2c interface.  Default I2C address is `0x40`.

An internal heater is available for high humidity environments.

Returns 3 values
* `temperature`
* `humidity`
* `dew point`

### SHT3x Temperature Sensor
The SHT3x has an i2c interface.  Common I2C addresses are `0x44` and `0x45`.

An internal heater is available for high humidity environments.

Returns 3 values
* `temperature`
* `humidity`
* `dew point`

### SHT40/41/45 Temperature Sensor
The SHT4x has an i2c interface.  Common I2C addresses are `0x44` and `0x45`.

An internal heater is available for high humidity environments.

Returns 3 values
* `temperature`
* `humidity`
* `dew point`

### HTU21D Temperature Sensor
The HTU21D has an i2c interface. Default I2C address is `0x40`.

Returns 3 values
* `temperature`
* `humidity`
* `dew point`

### HTU31D Temperature Sensor
The HTU31D has an i2c interface. Common I2C addresses are `0x40` and `0x41`.

An internal heater is available for high humidity environments.

Returns 3 values
* `temperature`
* `humidity`
* `dew point`

### AHT10/20 Temperature Sensor
The AHTx0 has an i2c interface.  Default I2C address is `0x38`.

Returns 3 values
* `temperature`
* `humidity`
* `dew point`


### SCD-30 Temperature Sensor
The SCD30 has an i2c interface. Default I2C address is `0x61`.

Returns 4 values
* `temperature`
* `humidity`
* `CO2`
* `dew point`


### SCD-4x Temperature Sensor
The SCD40 and SCD41 has an i2c interface. Default I2C address is `0x62`.

Returns 4 values
* `temperature`
* `humidity`
* `CO2`
* `dew point`


### AHT10/20 Temperature Sensor
The AHTx0 has an i2c interface.  Default I2C address is `0x38`.

Returns 3 values
* `temperature`
* `humidity`
* `dew point`


### HDC302x Temperature Sensor
The HDC302x has an i2c interface.  Common I2C addresses are `0x44`, `0x45`, `0x46`, and `0x47`.

Returns 2 values:
* `temperature`
* `pressure`


### TMP36 Temperature Sensor via ADS1x15 ADC
The ADS1x15 ADC has an i2c interface.  Common I2C addresses are `0x48`, `0x49`, `0x4a`, and `0x4b`

The ADC reads the analog voltage from the TMP36 sensor which is converted to the temperature value.

Returns 1 value
* `temperature`

### LM35 Temperature Sensor via ADS1x15 ADC
The ADS1x15 ADC has an i2c interface.  Common I2C addresses are `0x48`, `0x49`, `0x4a`, and `0x4b`

The ADC reads the analog voltage from the LM35 sensor which is converted to the temperature value.

Returns 1 value
* `temperature`

### MLX90614 Sky Temperature
This MLX90614 has an i2c interface.  Default i2c address is `0x5a`

Note:  My module was not detected with i2cdetect, but it still worked.

Returns 2 values:
* `temperature`
* `sky_temperature`

### MLX90615 Sky Temperature
This MLX90615 has an i2c interface.  Default i2c address is `0x5b`

Returns 2 values:
* `temperature`
* `sky_temperature`

### MLX90640 Thermal Camera
This MLX90640 has an i2c interface.  Default i2c address is `0x33`

Thermal image is TBD.

Returns 1 value:
* `avg_temperature`
  
### TSL2561 Light Sensor
The TSL2561 has an i2c interface.  Default i2c address is `0x39`

Returns 3 values:
* `lux`
* `broadband`
* `infrared`

### TSL2591 Light Sensor
The TSL2561 has an i2c interface.  Default i2c address is `0x29`

Returns 4 values:
* `lux`
* `visible`
* `infrared`
* `full_spectrum`


### VEML7700 Light Sensor
The VEML7700 has an i2c interface.  Default i2c address is `0x10`

Returns 4 values:
* `lux`
* `light`
* `white light`


### BH1750 Light Sensor
The BH1750 has an i2c interface.  Default i2c address is `0x23`

Returns 1 value:
* `lux`


### SI1145 UV Light Sensor
The SI1145 has an i2c interface.  Default i2c address is `0x60`

Returns 3 values:
* `visible`
* `ir`
* `uv index`


### LTR390 UV Light Sensor
The LTR390 has an i2c interface.  Default i2c address is `0x53`

Returns 4 values:
* `uv`
* `light`
* `uv index`
* `lux`


### MMC5983MA Magnetometer/Gauss Sensor
The MMC5983MA has an i2c interface.  Default i2c address is `0x30`

Returns 4 values:
* `x gauss`
* `y gauss`
* `z gauss`
* `temperature`


### ICM20x IMU Sensor
The ICM20x has an i2c interface.  Default I2C address is `0x68`

Returns 3 values:
* `X μT`
* `Y μT`
* `Z μT`


### MPU6050 IMU Sensor
The MPU6050 has an i2c interface.  Default I2C address is `0x68`

Returns 1 value:
* `temp`


### INA219 Current Sensor
The INA219 has an i2c interface.  Common I2C addresses are `0x40` (default), `0x41`, `0x42`, and `0x43`

Returns 3 values:
* `voltage`
* `current`
* `watts`


### INA228 Current Sensor
The INA228 has an i2c interface.  Common I2C addresses are `0x40` (default), `0x41`, `0x42`, and `0x43`

Returns 4 values:
* `voltage`
* `current`
* `watts`
* `die temperature`


### INA23x Current Sensor
The INA237 and INA238 have an i2c interface.  Common I2C addresses are `0x40` (default), `0x41`, `0x42`, and `0x43`

Returns 4 values:
* `voltage`
* `current`
* `watts`
* `die temperature`


### INA260 Current Sensor
The INA260 has an i2c interface.  Common I2C addresses are `0x40` (default), `0x41`, `0x42`, and `0x43`

Returns 3 values:
* `voltage`
* `current`
* `watts`


### INA3221 Current Sensor
The INA3221 has an i2c interface.  Common I2C addresses are `0x40` (default), `0x41`, `0x42`, and `0x43`

Returns 9 values:
* `channel 1 voltage`
* `channel 1 current`
* `channel 1 watts`
* `channel 2 voltage`
* `channel 2 current`
* `channel 2 watts`
* `channel 3 voltage`
* `channel 3 current`
* `channel 3 watts`


### SGP40 VOC Air Quality Sensor
The SGP40 has an i2c interface.  Default I2C address is `0x59`

Note: Gas readings are not temperature/humidity compensated.  There is no way to pass temp/humidity data to the module.

Note: May not be detected by `i2cdetect`

Returns 1 value:
* `gas (raw)`


### AS3935 Lightning Sensor
The AS3935 Lightning sensor has a SPI and i2c interface.  Common I2C addresses are `0x03` (default), `0x02`, and `0x01`

The recommended configuration is the SPI interface.  The i2c interface has some documented stability problems.

The AS3935 relies on interrupts to indicate when lightning strikes occur which requires a second GPIO pin.  In SPI mode, pin1 is CS, pin2 is INT.  In i2c mode, pin1 is not used (set any valid pin) and pin2 is INT.  Interrupt code uses `RPi.GPIO` therefore this will only on a Raspberry Pi.

Use the following command to scan the lower 7 addresses.
`i2cdetect -a -y 1 0x00 0x77`

Testing:  An electronic lighter or powering up a fluorescent light (with ballast) can be a decent test to see if the sensor responds.  These will usually be detected as noise, not lightning strikes.

Note:  The AS3935 module is basically a noise detector.  It is designed to detect EMF noise emissions that roughly correspond with what lightning strikes produce.  It is very susceptible to other noise.

Returns 4 values:
* `strike count`
* `minimum distance`
* `maximum distance`
* `average distance`
* `disturber count`
* `noise count`

| Pin  | I2C  | Note |
| ---- | ---- | ---- |
| VCC  |      | 3.3v |
| GND  |      |      |
| SCL  | SCL  | Raspi pin 5 (GPIO 3) |
| MOSI | SDA  | Raspi pin 3 (GPIO 2) |
| SI   | SI   | Low SPI, High i2c |



### Test Data Generator
This simulates a sensor with 7 data points.  For development systems.

Returns 7 values
* `add`
* `subtract`
* `fibonacci`
* `random`
* `sine wave (20-50)`
* `20`
* `30`