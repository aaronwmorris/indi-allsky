import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


def test_hook_and_adu_validators():
    # HOOK_TIMEOUT_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.HOOK_TIMEOUT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Timeout must be greater than 0'):
        forms.HOOK_TIMEOUT_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Timeout must be less than 20'):
        forms.HOOK_TIMEOUT_validator(None, DummyField(21))
    forms.HOOK_TIMEOUT_validator(None, DummyField(10))

    # TARGET_ADU_validator
    with pytest.raises(ValidationError, match='Target ADU must be greater than 0'):
        forms.TARGET_ADU_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Target ADU must be less than 255'):
        forms.TARGET_ADU_validator(None, DummyField(256))
    forms.TARGET_ADU_validator(None, DummyField(128))

    # TARGET_ADU_DAY_validator
    with pytest.raises(ValidationError, match='Target ADU must be greater than 0'):
        forms.TARGET_ADU_DAY_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Target ADU must be less than 255'):
        forms.TARGET_ADU_DAY_validator(None, DummyField(256))
    forms.TARGET_ADU_DAY_validator(None, DummyField(128))

    # TARGET_ADU_DEV_validator
    with pytest.raises(ValidationError, match='Target ADU Deviation must be greater than 0'):
        forms.TARGET_ADU_DEV_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Target ADU must be less than 100'):
        forms.TARGET_ADU_DEV_validator(None, DummyField(101))
    forms.TARGET_ADU_DEV_validator(None, DummyField(10))

    # TARGET_ADU_DEV_DAY_validator
    with pytest.raises(ValidationError, match='Target ADU Deviation must be greater than 0'):
        forms.TARGET_ADU_DEV_DAY_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Target ADU must be less than 100'):
        forms.TARGET_ADU_DEV_DAY_validator(None, DummyField(101))
    forms.TARGET_ADU_DEV_DAY_validator(None, DummyField(10))


def test_roi_and_fov_validators():
    # ADU_ROI_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.ADU_ROI_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='ADU Region of Interest must be 0 or greater'):
        forms.ADU_ROI_validator(None, DummyField(-1))
    forms.ADU_ROI_validator(None, DummyField(100))

    # SQM_ROI_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.SQM_ROI_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='SQM Region of Interest must be 0 or greater'):
        forms.SQM_ROI_validator(None, DummyField(-1))
    forms.SQM_ROI_validator(None, DummyField(100))

    # ADU_FOV_DIV_validator
    with pytest.raises(ValidationError, match='ADU FoV divisor must be 2, 3, 4, 5, or 6'):
        forms.ADU_FOV_DIV_validator(None, DummyField(5))
    forms.ADU_FOV_DIV_validator(None, DummyField(2))

    # SQM_FOV_DIV_validator
    with pytest.raises(ValidationError, match='SQM FoV divisor must be 2, 3, 4, 5, or 6'):
        forms.SQM_FOV_DIV_validator(None, DummyField(5))
    forms.SQM_FOV_DIV_validator(None, DummyField(4))


def test_detection_validators():
    # DETECT_STARS_THOLD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.DETECT_STARS_THOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Threshold must be greater than 0'):
        forms.DETECT_STARS_THOLD_validator(None, DummyField(0.0))
    with pytest.raises(ValidationError, match='Threshold must be 1.0 or less'):
        forms.DETECT_STARS_THOLD_validator(None, DummyField(1.5))
    forms.DETECT_STARS_THOLD_validator(None, DummyField(0.5))

    # DETECT_STARS_SEP_THOLD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.DETECT_STARS_SEP_THOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Sigma must be 0.5 or greater'):
        forms.DETECT_STARS_SEP_THOLD_validator(None, DummyField(0.4))
    with pytest.raises(ValidationError, match='Sigma must be 50.0 or less'):
        forms.DETECT_STARS_SEP_THOLD_validator(None, DummyField(51.0))
    forms.DETECT_STARS_SEP_THOLD_validator(None, DummyField(2.5))

    # DETECT_STARS_SEP_MAX_RADIUS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.DETECT_STARS_SEP_MAX_RADIUS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Max radius must be 1 or greater'):
        forms.DETECT_STARS_SEP_MAX_RADIUS_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Max radius must be 500 or less'):
        forms.DETECT_STARS_SEP_MAX_RADIUS_validator(None, DummyField(501))
    forms.DETECT_STARS_SEP_MAX_RADIUS_validator(None, DummyField(50))

    # DETECT_METEORS_THOLD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.DETECT_METEORS_THOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Threshold must be greater than 10'):
        forms.DETECT_METEORS_THOLD_validator(None, DummyField(10))
    with pytest.raises(ValidationError, match='Threshold must be 1000 or less'):
        forms.DETECT_METEORS_THOLD_validator(None, DummyField(1001))
    forms.DETECT_METEORS_THOLD_validator(None, DummyField(100))


def test_location_and_clahe_validators():
    # LOCATION_NAME_validator
    forms.LOCATION_NAME_validator(None, DummyField(''))
    forms.LOCATION_NAME_validator(None, DummyField('Observatory'))

    # LOCATION_LATITUDE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LOCATION_LATITUDE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Latitude must be greater than -90'):
        forms.LOCATION_LATITUDE_validator(None, DummyField(-91.0))
    with pytest.raises(ValidationError, match='Latitude must be less than 90'):
        forms.LOCATION_LATITUDE_validator(None, DummyField(91.0))
    forms.LOCATION_LATITUDE_validator(None, DummyField(35.0))

    # LOCATION_LONGITUDE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LOCATION_LONGITUDE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Longitude must be greater than -180'):
        forms.LOCATION_LONGITUDE_validator(None, DummyField(-181.0))
    with pytest.raises(ValidationError, match='Longitude must be less than 180'):
        forms.LOCATION_LONGITUDE_validator(None, DummyField(181.0))
    forms.LOCATION_LONGITUDE_validator(None, DummyField(139.0))

    # LOCATION_ELEVATION_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LOCATION_ELEVATION_validator(None, DummyField('abc'))
    forms.LOCATION_ELEVATION_validator(None, DummyField(100))

    # CLAHE_CLIPLIMIT_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CLAHE_CLIPLIMIT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Clip limit must be greater than 0'):
        forms.CLAHE_CLIPLIMIT_validator(None, DummyField(0.0))
    with pytest.raises(ValidationError, match='Clip limit must be less than 60'):
        forms.CLAHE_CLIPLIMIT_validator(None, DummyField(61.0))
    forms.CLAHE_CLIPLIMIT_validator(None, DummyField(2.0))

    # CLAHE_GRIDSIZE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CLAHE_GRIDSIZE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Grid size must be 4 or greater'):
        forms.CLAHE_GRIDSIZE_validator(None, DummyField(3))
    with pytest.raises(ValidationError, match='Clip limit must be 64 or less'):
        forms.CLAHE_GRIDSIZE_validator(None, DummyField(65))
    forms.CLAHE_GRIDSIZE_validator(None, DummyField(8))


def test_night_sun_and_label_validators():
    # NIGHT_SUN_ALT_DEG_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.NIGHT_SUN_ALT_DEG_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Sun altitude must be greater than -90'):
        forms.NIGHT_SUN_ALT_DEG_validator(None, DummyField(-91.0))
    with pytest.raises(ValidationError, match='Sun altitude must be less than 90'):
        forms.NIGHT_SUN_ALT_DEG_validator(None, DummyField(91.0))
    forms.NIGHT_SUN_ALT_DEG_validator(None, DummyField(-6.0))

    # NIGHT_MOONMODE_ALT_DEG_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.NIGHT_MOONMODE_ALT_DEG_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Moon altitude must be greater than -90'):
        forms.NIGHT_MOONMODE_ALT_DEG_validator(None, DummyField(-91.0))
    with pytest.raises(ValidationError, match='Moon altitude must be less than 90'):
        forms.NIGHT_MOONMODE_ALT_DEG_validator(None, DummyField(92.0))
    forms.NIGHT_MOONMODE_ALT_DEG_validator(None, DummyField(10.0))

    # NIGHT_MOONMODE_PHASE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.NIGHT_MOONMODE_PHASE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Moon illumination must be 0 or greater'):
        forms.NIGHT_MOONMODE_PHASE_validator(None, DummyField(-1.0))
    with pytest.raises(ValidationError, match='Moon illumination must be 100 or less'):
        forms.NIGHT_MOONMODE_PHASE_validator(None, DummyField(101.0))
    forms.NIGHT_MOONMODE_PHASE_validator(None, DummyField(50.0))

    # IMAGE_LABEL_SYSTEM_validator
    forms.IMAGE_LABEL_SYSTEM_validator(None, DummyField(''))
    forms.IMAGE_LABEL_SYSTEM_validator(None, DummyField('opencv'))
    forms.IMAGE_LABEL_SYSTEM_validator(None, DummyField('pillow'))
    with pytest.raises(ValidationError, match='Unknown label system'):
        forms.IMAGE_LABEL_SYSTEM_validator(None, DummyField('invalid'))
