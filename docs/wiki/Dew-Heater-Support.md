# Overview
The dew heater support in indi-allsky is intended to use the GPIO or PWM pins from a SBC such as a Raspberry PI to drive either a MOSFET or relay to manage the dew heater state.

The default functionality is to activate the dew heater at night and deactivate during the day, although it is possible to enable day time operation.

It is also possible to operate the dew heater using temperature thresholds if you have an appropriate temperature sensor.  The default target temperature is the dew point, which will be available if you have a sensor that detects both temperature and relative humidity [RH].  If you do not, you may set a manual temperature threshold.

Note:  The manual threshold does not need to be a temperature.  You may select any of the user data slots, which could be a RH value.

## GPIO Permissions
If you receive a `PermissionDenied` exception when accessing GPIO pins

https://github.com/aaronwmorris/indi-allsky/wiki/GPIO-Permissions

## WARNING
**The pins from a SBC cannot be used to directly drive a dew heater.  Trying to do so WILL damage your system.**

## Testing Dew Heaters
The following test script can be used to test your dew heater for proper wiring and operation.  Dew Heaters can be difficult to detect operation if you do not have an oscilloscope or thermal camera.  An LED is probably the best option to get feedback from the system.

```
source virtualenv/indi-allsky/bin/activate

./misc/device_test.py dew_heater
```

## Dew Heater - Standard
This type of dew heater only supports two modes:  ON and OFF.  Any duty cycle applied to this dew heater will set it to FULL power.  This type may use either a relay or MOSFET driver.

## Dew Heater - PWM
The PWM dew heater may be set to different power levels by utilizing the hardware PWM support from the SBC pins.  This type requires the use of a MOSFET driver.  A relay will not work.

## Dew Heater - Software PWM
PWM control is software managed by either the `RPi.GPIO` or `gpiozero` modules.  The frequency is much more limited with Software PWM.  The default frequency is 100Hz.

## Adafruit Motor Shield/Hat
Support for the Motor Shield (various models) with the PCA9685 PWM driver is supported by the Adafruit MotorKit python driver.  The Motor Shield is controlled via I2C.  The default I2C address is `0x60`

| Possible pin values |
| ------------------- |
| `motor1`            |
| `motor2`            |
| `motor3`            |
| `motor4`            |

### Note about Motor Shield concurrent access
The Motor Shield may be used for both the focus controller and Dew Heater and Fan drivers, however, it will likely not be possible to utilize the focus/stepper capability while the fan and dew heater is active.  The focus controller runs in the web interface, while dew heater/fan runs in the capture process.  Trying to access the same i2c device across multiple processes will likely fail.

## DockerPi 4 Channel Relay
The DockerPi 4 Channel Relay hat has individually controlled relays that are addressable at different i2c addresses.

| Channel | Address |
| ------- | ------- |
| Relay 1 | `0x10`  |
| Relay 2 | `0x11`  |
| Relay 3 | `0x12`  |
| Relay 4 | `0x13`  |


## MQTT Dew Heater Management
The MQTT support is for situations where the camera is remote from the indi-allsky capture instance.  The dew heater will be controlled by a remote script that monitors the MQTT topics for the expected dew heater state.

The dew heater `Pin` in the config will be used as the MQTT topic name for publishing.

The `./misc/mqtt_remote_dew_heater_fan.py` script may be used to operate the dew heater and fan on the remote system.

Monitor dew heater and fan topic manually:
```
mosquitto_sub -d -V mqttv5 -F %j -h localhost -p 1883 -u mqtt_username -P password123 -t "dew_heater_topic" -t "fan_topic"
```


### Raspberry Pi 5
#### Raspberry Pi 5 - RuntimeError: Cannot determine SOC peripheral base address
```
source virtualenv/indi-allsky/bin/activate

pip uninstall RPi.GPIO rpi.lgpio

pip install --upgrade rpi.lgpio
```

### System virtualenv
If your virtualenv uses system python modules (like with indi_pylibcamera), it may be necessary to remove certain system python packages.  _This is not normally required._

```
sudo apt-get remove python3-rpi.gpio python3-lgpio python3-gpiozero python3-pigpio
```