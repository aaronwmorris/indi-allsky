from .dewHeaterSimulator import DewHeaterSimulator as dew_heater_simulator
from .dewHeaterPwm import DewHeaterPwm as blinka_dew_heater_pwm
from .dewHeaterStandard import DewHeaterStandard as blinka_dew_heater_standard
from .dewHeaterStandard import DewHeaterStandard as blinka_dew_heater_digital

from .dewHeaterSoftwarePwm import DewHeaterSoftwarePwmRpiGpio as rpigpio_dew_heater_software_pwm
from .dewHeaterSoftwarePwm import DewHeaterSoftwarePwmGpiozero as gpiozero_dew_heater_software_pwm

from .dewHeaterMotorKit import DewHeaterMotorKitPwm as motorkit_dew_heater_pwm
from .dewHeaterDockerPi4ChannelRelay import DewHeaterDockerPi4ChannelRelay_I2C as dew_heater_dockerpi_4channel_relay

from .dewHeaterSerialPwm import DewHeaterSerialPwm as serial_dew_heater_pwm


__all__ = (
    'dew_heater_simulator',
    'blinka_dew_heater_pwm',
    'blinka_dew_heater_standard',
    'blinka_dew_heater_digital',  # legacy name
    'dew_heater_dockerpi_4channel_relay',
    'serial_dew_heater_pwm',
    'rpigpio_dew_heater_software_pwm',
    'gpiozero_dew_heater_software_pwm',
    'motorkit_dew_heater_pwm',
)
