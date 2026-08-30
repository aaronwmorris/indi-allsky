import math


EXPOSURE_MODE_BASIC = 'exposure_basic'
EXPOSURE_MODE_LEGACY = 'exposure_legacy_autogain'
EXPOSURE_MODE_DB_1_10 = 'exposure_autogain_exp_prio_db_1_10'
EXPOSURE_MODE_DB = 'exposure_autogain_exp_prio_db'
EXPOSURE_MODE_ISO = 'exposure_autogain_exp_prio_iso'
EXPOSURE_MODE_ISO_1_100 = 'exposure_autogain_exp_prio_iso_1_100'


EXPOSURE_MODE_LABELS = {
    EXPOSURE_MODE_BASIC: 'Fixed gains',
    EXPOSURE_MODE_LEGACY: 'Legacy auto-gain',
    EXPOSURE_MODE_DB_1_10: 'Exposure priority (1/10 dB)',
    EXPOSURE_MODE_DB: 'Exposure priority (native dB)',
    EXPOSURE_MODE_ISO: 'Exposure priority (native ISO)',
    EXPOSURE_MODE_ISO_1_100: 'Exposure priority (1/100 ISO)',
}


CONTINUOUS_AUTO_GAIN_MODES = frozenset((
    EXPOSURE_MODE_DB_1_10,
    EXPOSURE_MODE_DB,
    EXPOSURE_MODE_ISO,
    EXPOSURE_MODE_ISO_1_100,
))


def gain_to_db(exposure_mode, gain):
    gain = float(gain)

    if exposure_mode == EXPOSURE_MODE_DB_1_10:
        return gain / 10.0

    if exposure_mode == EXPOSURE_MODE_DB:
        return gain

    if exposure_mode == EXPOSURE_MODE_ISO:
        if gain <= 0:
            raise ValueError('Native ISO gain must be greater than zero')
        return 20 * math.log10(gain / 100)

    if exposure_mode == EXPOSURE_MODE_ISO_1_100:
        if gain <= 0:
            raise ValueError('1/100 ISO gain must be greater than zero')
        return 20 * math.log10(gain)

    raise ValueError('Exposure mode does not use a dB gain mapping: {0:s}'.format(exposure_mode))


def db_to_gain(exposure_mode, gain_db):
    gain_db = float(gain_db)

    if exposure_mode == EXPOSURE_MODE_DB_1_10:
        return gain_db * 10.0

    if exposure_mode == EXPOSURE_MODE_DB:
        return gain_db

    if exposure_mode == EXPOSURE_MODE_ISO:
        return 100 * (10 ** (gain_db / 20))

    if exposure_mode == EXPOSURE_MODE_ISO_1_100:
        return 10 ** (gain_db / 20)

    raise ValueError('Exposure mode does not use a dB gain mapping: {0:s}'.format(exposure_mode))
