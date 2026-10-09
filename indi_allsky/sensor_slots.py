"""Alphabetical device slots using the existing TEMP_SENSOR configuration keys."""

SENSOR_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
SENSOR_FIELDS = ('CLASSNAME', 'LABEL', 'PIN_1', 'PIN_2', 'USER_VAR_SLOT', 'I2C_ADDRESS', 'TITLE_TEMPLATE')
SENSOR_DEFAULTS = {
    letter: {
        'CLASSNAME': '',
        'LABEL': 'Sensor {0}'.format(letter),
        'PIN_1': pin,
        'PIN_2': '',
        'USER_VAR_SLOT': 'sensor_user_{0}'.format(slot),
        'I2C_ADDRESS': address,
        'TITLE_TEMPLATE': '{name:s} - {label:s} - {probe:s}',
    }
    for letter, (pin, slot, address) in zip(SENSOR_LETTERS, (
        ('D5', 10, '0x77'), ('D6', 20, '0x76'), ('D16', 30, '0x40'),
        ('D26', 40, '0x50'), ('D25', 50, '0x51'), ('D27', 55, '0x52'),
    ) + (('', 10, '0x40'),) * 20)
}


def sensor_form_data(config):
    settings = config.get('TEMP_SENSOR', {})
    return {
        'TEMP_SENSOR__{0}_{1}'.format(letter, field): settings.get('{0}_{1}'.format(letter, field), default)
        for letter, defaults in SENSOR_DEFAULTS.items() for field, default in defaults.items()
    }


def initialize_sensors(config, night_av, astro_av):
    import logging
    from . import constants
    from .devices import sensors
    from .devices.exceptions import DeviceControlException, SensorException

    devices = []
    settings = config.get('TEMP_SENSOR', {})
    for letter, defaults in SENSOR_DEFAULTS.items():
        classname = settings.get(letter + '_CLASSNAME')
        if not classname and letter > 'F':
            continue
        if not classname:
            sensor = sensors.sensor_simulator(config, defaults['LABEL'], night_av, astro_av)
        else:
            try:
                sensor_class = getattr(sensors, classname)
                sensor = sensor_class(
                    config, settings.get(letter + '_LABEL', defaults['LABEL']), night_av, astro_av,
                    pin_1_name=settings.get(letter + '_PIN_1', 'notdefined'),
                    pin_2_name=settings.get(letter + '_PIN_2', 'notdefined'),
                    i2c_address=settings.get(letter + '_I2C_ADDRESS', defaults['I2C_ADDRESS']),
                )
            except (AttributeError, DeviceControlException, SensorException) as e:
                logging.getLogger('indi_allsky').error('Error initializing sensor %s: %s', letter, str(e))
                sensor = sensors.sensor_simulator(config, defaults['LABEL'], night_av, astro_av)
        sensor.slot = constants.SENSOR_INDEX_MAP[settings.get(letter + '_USER_VAR_SLOT', defaults['USER_VAR_SLOT'])]
        devices.append(sensor)
    return devices
