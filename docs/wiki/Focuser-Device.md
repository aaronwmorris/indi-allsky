# Overview
indi-allsky has the ability to control an electronic focuser mechanism to adjust the focus of all sky cameras.

## GPIO Permissions
If you receive a `PermissionDenied` exception when accessing GPIO pins

https://github.com/aaronwmorris/indi-allsky/wiki/GPIO-Permissions

## Support Matrix
| Device                  | Note |
| ----------------------- | ---- |
| 28BYJ-48 Stepper        | Working |
| A4988 w/ NEMA17         | Not tested |
| Adafruit Motor Shield   | Not tested |

## 28BYJ-48 Stepper Motor
This is a common and inexpensive stepper motor that is commonly distributed with a ULN2003 driver.  This configuration only requires 4 GPIO pins (+GND and Power).

The 28BYJ-48 Stepper Motor has multiple variations, but the 1/64 geared is the most common variety.  If you have one where the gear ratio is not supported, please open an issue and we can add the version.

https://ben.akrin.com/driving-a-28byj-48-stepper-motor-uln2003-driver-with-a-raspberry-pi/

| GPIO Pin     | Driver Pin     |
| ------------ | -------------- |
| GPIO Pin 1   | IN1            |
| GPIO Pin 2   | IN2            |
| GPIO Pin 3   | IN3            |
| GPIO Pin 4   | IN4            |


## NEMA17 Stepper Motor with A4988 controller
The NEMA17 stepper motor support 200 steps per revolution (1.8 degrees per step) in full step mode.  This configuration requires only 2 GPIO pins in full step mode.  One additional GPIO pin may be used for half step (0.9 degrees/step) mode.

| GPIO Pin     | AS4988 Pin     |
| ------------ | -------------- |
| GPIO Pin 1   | STEP           |
| GPIO Pin 2   | DIR            |
| GPIO Pin 3   | MS1 (optional) |
| GPIO Pin 4   | Unused         |

## Adafruit Motor Shield/Hat
Support for the Motor Shield (various models) with the PCA9685 PWM driver is supported by the Adafruit MotorKit python driver.  The Motor Shield is controlled via I2C.  The default I2C address is `0x60`

| Possible pin values |
| ------------------- |
| `stepper1`          |
| `stepper2`          |

### Note about Motor Shield concurrent access
The Motor Shield may be used for both the focus controller and Dew Heater and Fan drivers, however, it will likely not be possible to utilize the focus/stepper capability while the fan and dew heater is active.  The focus controller runs in the web interface, while dew heater/fan runs in the capture process.  Trying to access the same i2c device across multiple processes will likely fail.
