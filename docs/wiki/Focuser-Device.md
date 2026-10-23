# Mechanical Focusers

`indi-allsky` supports electronic focuser mechanisms to automate and fine-tune lens optical focus directly from the web interface or via command-line utilities.

Focusers are configured in the web interface under **Configuration** → **Focuser**.

---

## 1. Supported Focuser Hardware

| Driver Class | Supported Controller / Motor | Interface | Typical Pin Configuration |
|---|---|---|---|
| `focuser_28byj` | 28BYJ-48 Stepper with ULN2003 Driver | 4 GPIO Pins | Pin 1: IN1, Pin 2: IN2, Pin 3: IN3, Pin 4: IN4 |
| `focuser_a4988` | A4988 / DRV8825 with NEMA 14 / NEMA 17 | 2–3 GPIO Pins | Pin 1: STEP, Pin 2: DIR, Pin 3: MS1 (Optional half-stepping) |
| `focuserMotorKit` | Adafruit Motor Shield / Motor FeatherWing (PCA9685) | I2C (`0x60`) | `stepper1` or `stepper2` channel |
| `focuserSerial28byj` | Arduino / Custom Serial Microcontroller | USB / Serial | Serial device path (e.g. `/dev/ttyUSB0` or `/dev/ttyACM0`) |
| `focuserSimulator` | Software Simulation Driver | Software | Virtual device for interface testing |

---

## 2. Wiring & Controller Details

### 28BYJ-48 Stepper with ULN2003 Driver
The 28BYJ-48 is an inexpensive 5V geared unipolar stepper motor (most commonly 1:64 reduction ratio) driven by a ULN2003 Darlington transistor array:
* Connect 5V and GND to the board power rail.
* Connect IN1, IN2, IN3, and IN4 to four available GPIO pins (e.g., `D17`, `D18`, `D27`, `D22`).
* Ensure appropriate [GPIO Permissions](GPIO-Permissions) are granted to the `indi-allsky` service user.

### A4988 / DRV8825 Bipolar Stepper Driver
For higher-torque NEMA 14 or NEMA 17 stepper motors:
* **STEP**: Pulses motor position (1 pulse = 1 step).
* **DIR**: Logic level sets clockwise or counter-clockwise rotation.
* **MS1 / MS2 / MS3**: (Optional) Microstepping selection pins.

### Adafruit MotorKit (I2C)
The Adafruit Motor Shield uses I2C communication (default address `0x60`).
> [!WARNING]
> If utilizing the Adafruit MotorKit for both focuser control and dew heaters/fans, ensure that I2C bus concurrency conflicts do not occur between the capture process and web worker processes.

---

## 3. Web Interface Focus Calibration

In the web interface:
1. Navigate to **Tools** → **Focus Assistant**.
2. Select target step increments (`1`, `10`, `50`, `100` steps) and direction (In / Out).
3. Inspect live star metrics (FWHM, HFD, and SEP star counts) as focus position varies to identify the critical focus zone.
