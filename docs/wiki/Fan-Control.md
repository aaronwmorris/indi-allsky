# Overview
The fan controller support in indi-allsky is intended to use the GPIO or PWM pins from a SBC such as a Raspberry PI to drive either a MOSFET or relay to manage the fan state.

> [!NOTE]
> Cooling fan controls are configured under **Configuration** → **Devices**. Basic driver and target temperature options appear in Simple Mode; advanced PWM frequencies, multi-stage threshold differentials, and hold timers require **Expert Mode** to be enabled via the top header switch.

The default functionality is to activate the fan during the day and deactivate at night, although it is possible to enable night time operation.

It is also possible to control the fan using temperature thresholds if you have an appropriate temperature sensor.


## GPIO Permissions
If you encounter a `PermissionDenied` error when accessing GPIO lines or character devices, review:
[`GPIO Permissions`](GPIO-Permissions.md)

## Hardware Warning
> [!CAUTION]
> Single Board Computer GPIO pins (3.3V logic) cannot source sufficient current to drive fan motors directly. Inductive flyback can permanently destroy SoC GPIO banks. Always utilize a dedicated logic-level MOSFET circuit or relay board.

## Testing Fans
Verify fan circuit operation and pin mapping using the diagnostic test tool:

### Debian Package (`.deb`) Installations
```bash
sudo indi-allsky-ctl test-devices fan
```

### Source / Git (`setup.sh`) Installations
```bash
source /var/lib/indi-allsky/virtualenv/bin/activate
# Or from git checkout: source virtualenv/indi-allsky/bin/activate

python ./misc/device_test.py fan
```

## Fan - Standard
This type of fan only supports two modes:  ON and OFF.  Any duty cycle applied to the fan will set it to FULL power.  This type may use either a relay or MOSFET driver.

## Fan - PWM
The PWM fan may be set to different power levels by utilizing the hardware PWM support from the SBC pins.  This type requires the use of a MOSFET driver.  A relay will not work.

## Fan - Software PWM
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


## MQTT Fan Management
The MQTT support is for situations where the camera is remote from the indi-allsky capture instance.  The fan will be controlled by a remote script that monitors the MQTT topics for the expected dew heater state.

The fan `Pin` in the config will be used as the MQTT topic name for publishing.

The `./misc/mqtt_remote_dew_heater_fan.py` script may be used to operate the dew heater and fan on the remote system.

Monitor dew heater and fan topic manually:
```
mosquitto_sub -d -V mqttv5 -F %j -h localhost -p 1883 -u mqtt_username -P password123 -t "dew_heater_topic" -t "fan_topic"
```


### Raspberry Pi 5
~~PWM support is not quite working yet.~~

PWM appears to be working as of Sept 2024.


#### Raspberry Pi 5 - RuntimeError: Cannot determine SOC peripheral base address

> [!IMPORTANT]
> **Debian Package (`.deb`) Users**: Do **NOT** run `pip` or modify virtualenvs manually. The Debian package already bundles pre-compiled, compatible GPIO and `rpi.lgpio` drivers inside `/var/lib/indi-allsky/venv/`. Manual pip modifications will break the package virtual environment. The steps below apply **only** to manual git source checkouts.

```bash
source virtualenv/indi-allsky/bin/activate

pip uninstall RPi.GPIO rpi.lgpio

pip install --upgrade rpi.lgpio
```

### System virtualenv
If your virtualenv uses system python modules (like with indi_pylibcamera), it may be necessary to remove certain system python packages.  _This is not normally required._

```
sudo apt-get remove python3-rpi.gpio python3-lgpio python3-gpiozero python3-pigpio
```