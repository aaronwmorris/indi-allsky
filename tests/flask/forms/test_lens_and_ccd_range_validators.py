import math
import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


def test_lens_validators_ranges():
    # LENS_NAME_validator
    forms.LENS_NAME_validator(None, DummyField(''))
    forms.LENS_NAME_validator(None, DummyField('Lens 1'))

    # LENS_FOCAL_LENGTH_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LENS_FOCAL_LENGTH_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Focal length must be greater than 0'):
        forms.LENS_FOCAL_LENGTH_validator(None, DummyField(0.0))
    forms.LENS_FOCAL_LENGTH_validator(None, DummyField(50.0))

    # LENS_FOCAL_RATIO_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LENS_FOCAL_RATIO_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Focal ratio must be greater than 0'):
        forms.LENS_FOCAL_RATIO_validator(None, DummyField(0.0))
    forms.LENS_FOCAL_RATIO_validator(None, DummyField(1.8))

    # LENS_IMAGE_CIRCLE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LENS_IMAGE_CIRCLE_validator(None, DummyField(12.5))
    with pytest.raises(ValidationError, match='Focal ratio must be greater than 0'):
        forms.LENS_IMAGE_CIRCLE_validator(None, DummyField(0))
    forms.LENS_IMAGE_CIRCLE_validator(None, DummyField(1000))

    # LENS_OFFSET_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LENS_OFFSET_validator(None, DummyField('abc'))
    forms.LENS_OFFSET_validator(None, DummyField(10))

    # LENS_ALTITUDE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LENS_ALTITUDE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Altitude must be 0 or greater'):
        forms.LENS_ALTITUDE_validator(None, DummyField(-1.0))
    with pytest.raises(ValidationError, match='Altitude must be 90 or less'):
        forms.LENS_ALTITUDE_validator(None, DummyField(91.0))
    forms.LENS_ALTITUDE_validator(None, DummyField(45.0))

    # LENS_AZIMUTH_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LENS_AZIMUTH_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Azimuth must be 0 or greater'):
        forms.LENS_AZIMUTH_validator(None, DummyField(-1.0))
    with pytest.raises(ValidationError, match='Azimuth must be 360 or less'):
        forms.LENS_AZIMUTH_validator(None, DummyField(361.0))
    forms.LENS_AZIMUTH_validator(None, DummyField(180.0))


def test_ccd_and_exposure_validators_ranges():
    # CCD_GAIN_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CCD_GAIN_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Gain must be 0 or higher'):
        forms.CCD_GAIN_validator(None, DummyField(-1))
    forms.CCD_GAIN_validator(None, DummyField(100))

    # CCD_BINNING_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CCD_BINNING_validator(None, DummyField(1.5))
    with pytest.raises(ValidationError, match='Bin mode must be more than 0'):
        forms.CCD_BINNING_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Bin mode must be less than 4'):
        forms.CCD_BINNING_validator(None, DummyField(5))
    forms.CCD_BINNING_validator(None, DummyField(2))

    # CCD_EXPOSURE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CCD_EXPOSURE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Default Exposure must be 0 or more'):
        forms.CCD_EXPOSURE_validator(None, DummyField(-1.0))
    with pytest.raises(ValidationError, match='Default Exposure cannot be more than 120'):
        forms.CCD_EXPOSURE_validator(None, DummyField(121.0))
    forms.CCD_EXPOSURE_validator(None, DummyField(30.0))

    # CAMERA_SQM__EXPOSURE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CAMERA_SQM__EXPOSURE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='SQM Exposure must be 1.0 or greater'):
        forms.CAMERA_SQM__EXPOSURE_validator(None, DummyField(0.5))
    with pytest.raises(ValidationError, match='SQM Exposure must be 60.0 or less'):
        forms.CAMERA_SQM__EXPOSURE_validator(None, DummyField(61.0))
    forms.CAMERA_SQM__EXPOSURE_validator(None, DummyField(10.0))

    # CCD_EXPOSURE_TIMEOUT_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CCD_EXPOSURE_TIMEOUT_validator(None, DummyField(120.5))
    with pytest.raises(ValidationError, match='Timeout must be 120 or more'):
        forms.CCD_EXPOSURE_TIMEOUT_validator(None, DummyField(100))
    forms.CCD_EXPOSURE_TIMEOUT_validator(None, DummyField(150))

    # EXPOSURE_PERIOD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.EXPOSURE_PERIOD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Exposure period must be 1.0 or more'):
        forms.EXPOSURE_PERIOD_validator(None, DummyField(0.5))
    forms.EXPOSURE_PERIOD_validator(None, DummyField(5.0))

    # EXPOSURE_PERIOD_DAY_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.EXPOSURE_PERIOD_DAY_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Exposure period must be 1.0 or more'):
        forms.EXPOSURE_PERIOD_DAY_validator(None, DummyField(0.5))
    forms.EXPOSURE_PERIOD_DAY_validator(None, DummyField(5.0))

    # CAMERA_SQM__EXPOSURE_PERIOD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CAMERA_SQM__EXPOSURE_PERIOD_validator(None, DummyField(60.5))
    with pytest.raises(ValidationError, match='Value must be 120 or more'):
        forms.CAMERA_SQM__EXPOSURE_PERIOD_validator(None, DummyField(30))
    forms.CAMERA_SQM__EXPOSURE_PERIOD_validator(None, DummyField(120))

    # SQM_MAGNITUDE_OFFSET_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.SQM_MAGNITUDE_OFFSET_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0 or more'):
        forms.SQM_MAGNITUDE_OFFSET_validator(None, DummyField(-1.0))
    forms.SQM_MAGNITUDE_OFFSET_validator(None, DummyField(0.0))


def test_timelapse_and_image_validators_ranges():
    # TIMELAPSE_SKIP_FRAMES_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.TIMELAPSE_SKIP_FRAMES_validator(None, DummyField(1.5))
    with pytest.raises(ValidationError, match='Skip frames must 0 or more'):
        forms.TIMELAPSE_SKIP_FRAMES_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Skip frames must 10 or less'):
        forms.TIMELAPSE_SKIP_FRAMES_validator(None, DummyField(11))
    forms.TIMELAPSE_SKIP_FRAMES_validator(None, DummyField(3))

    # TIMELAPSE__IMAGE_CIRCLE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.TIMELAPSE__IMAGE_CIRCLE_validator(None, DummyField(100.5))
    with pytest.raises(ValidationError, match='Diameter must be 100 or greater'):
        forms.TIMELAPSE__IMAGE_CIRCLE_validator(None, DummyField(50))
    forms.TIMELAPSE__IMAGE_CIRCLE_validator(None, DummyField(500))

    # TIMELAPSE__KEOGRAM_RATIO_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.TIMELAPSE__KEOGRAM_RATIO_validator(None, DummyField(1))
    with pytest.raises(ValidationError, match='Ratio must be 0.01 or greater'):
        forms.TIMELAPSE__KEOGRAM_RATIO_validator(None, DummyField(0.005))
    with pytest.raises(ValidationError, match='Ratio must be 0.33 or less'):
        forms.TIMELAPSE__KEOGRAM_RATIO_validator(None, DummyField(0.5))
    forms.TIMELAPSE__KEOGRAM_RATIO_validator(None, DummyField(0.15))

    # TIMELAPSE__PRE_SCALE_validator
    with pytest.raises(ValidationError, match='Pre-Scaling factor must be greater than 0'):
        forms.TIMELAPSE__PRE_SCALE_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Pre-Scaling factor must be 100 or less'):
        forms.TIMELAPSE__PRE_SCALE_validator(None, DummyField(101))
    forms.TIMELAPSE__PRE_SCALE_validator(None, DummyField(50))

    # CCD_BIT_DEPTH_validator
    with pytest.raises(ValidationError, match='Bits must be'):
        forms.CCD_BIT_DEPTH_validator(None, DummyField(9))
    forms.CCD_BIT_DEPTH_validator(None, DummyField(16))

    # CCD_TEMP_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CCD_TEMP_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Temperature must be greater than -50'):
        forms.CCD_TEMP_validator(None, DummyField(-55))
    forms.CCD_TEMP_validator(None, DummyField(20))

    # FOCUS_DELAY_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FOCUS_DELAY_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Focus delay must be 1.0 or more'):
        forms.FOCUS_DELAY_validator(None, DummyField(0.5))
    forms.FOCUS_DELAY_validator(None, DummyField(2.0))


def test_color_and_processing_validators_ranges():
    # WB_FACTOR_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.WB_FACTOR_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Balance factor must be 0 or greater'):
        forms.WB_FACTOR_validator(None, DummyField(-0.5))
    with pytest.raises(ValidationError, match='Balance factor must be less than 4.0'):
        forms.WB_FACTOR_validator(None, DummyField(4.5))
    forms.WB_FACTOR_validator(None, DummyField(1.5))

    # WB_MTF_MIDTONES_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.WB_MTF_MIDTONES_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0.0 or more'):
        forms.WB_MTF_MIDTONES_validator(None, DummyField(-0.1))
    with pytest.raises(ValidationError, match='Value must be 1.0 or less'):
        forms.WB_MTF_MIDTONES_validator(None, DummyField(1.2))
    forms.WB_MTF_MIDTONES_validator(None, DummyField(0.5))

    # SATURATION_FACTOR_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.SATURATION_FACTOR_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Saturation factor must be 0 or greater'):
        forms.SATURATION_FACTOR_validator(None, DummyField(-0.1))
    with pytest.raises(ValidationError, match='Saturation factor must be less than 4.0'):
        forms.SATURATION_FACTOR_validator(None, DummyField(4.5))
    forms.SATURATION_FACTOR_validator(None, DummyField(1.2))

    # GAMMA_CORRECTION_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.GAMMA_CORRECTION_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Gamma most be greater than 0'):
        forms.GAMMA_CORRECTION_validator(None, DummyField(0.0))
    forms.GAMMA_CORRECTION_validator(None, DummyField(1.0))

    # SHARPEN_AMOUNT_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.SHARPEN_AMOUNT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Sharpen amount must be 0 or greater'):
        forms.SHARPEN_AMOUNT_validator(None, DummyField(-0.5))
    with pytest.raises(ValidationError, match='Sharpen amount must be 2.0 or less'):
        forms.SHARPEN_AMOUNT_validator(None, DummyField(2.5))
    forms.SHARPEN_AMOUNT_validator(None, DummyField(1.0))

    # SCNR_MTF_MIDTONES_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.SCNR_MTF_MIDTONES_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Value must be 0.5 or more'):
        forms.SCNR_MTF_MIDTONES_validator(None, DummyField(0.4))
    with pytest.raises(ValidationError, match='Value must be 1.0 or less'):
        forms.SCNR_MTF_MIDTONES_validator(None, DummyField(1.1))
    forms.SCNR_MTF_MIDTONES_validator(None, DummyField(0.75))

    # IMAGE_DENOISE_STRENGTH_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_DENOISE_STRENGTH_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Strength must be 1 or more'):
        forms.IMAGE_DENOISE_STRENGTH_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Strength must be 5 or less'):
        forms.IMAGE_DENOISE_STRENGTH_validator(None, DummyField(6))
    forms.IMAGE_DENOISE_STRENGTH_validator(None, DummyField(3))

    # BILATERAL_SIGMA_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.BILATERAL_SIGMA_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Sigma must be 1 or more'):
        forms.BILATERAL_SIGMA_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Sigma must be 50 or less'):
        forms.BILATERAL_SIGMA_validator(None, DummyField(51))
    forms.BILATERAL_SIGMA_validator(None, DummyField(10))

    # IMAGE_CALIBRATE_HOLE_THOLD_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_CALIBRATE_HOLE_THOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Threshold must be greater than 0'):
        forms.IMAGE_CALIBRATE_HOLE_THOLD_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Threshold must be less than 100'):
        forms.IMAGE_CALIBRATE_HOLE_THOLD_validator(None, DummyField(101))
    forms.IMAGE_CALIBRATE_HOLE_THOLD_validator(None, DummyField(50))


def test_asi676mc_repair_validators():
    # IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator
    with pytest.raises(ValidationError, match='Enter a number'):
        forms.IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Enter a number'):
        forms.IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator(None, DummyField(math.nan))
    with pytest.raises(ValidationError, match='Enter a value greater than 0'):
        forms.IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Enter a value no greater than'):
        forms.IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator(None, DummyField(99999999.0))
    forms.IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator(None, DummyField(2.0))

    # IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator
    with pytest.raises(ValidationError, match='Enter a whole number'):
        forms.IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator(None, DummyField(2.5))
    with pytest.raises(ValidationError, match='Enter an even number'):
        forms.IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator(None, DummyField(1))
    with pytest.raises(ValidationError, match='Enter an even number'):
        forms.IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator(None, DummyField(3))
    with pytest.raises(ValidationError, match='Enter an even number'):
        forms.IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator(None, DummyField(2000))
    forms.IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator(None, DummyField(4))

    # IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD_validator
    with pytest.raises(ValidationError, match='Enter a whole number'):
        forms.IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Enter a value between 1 and 65535'):
        forms.IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Enter a value between 1 and 65535'):
        forms.IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD_validator(None, DummyField(70000))
    forms.IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD_validator(None, DummyField(60000))

    # IMAGE_ASI676MC_REPAIR__GAIN_validator
    with pytest.raises(ValidationError, match='Enter a number'):
        forms.IMAGE_ASI676MC_REPAIR__GAIN_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Enter a number'):
        forms.IMAGE_ASI676MC_REPAIR__GAIN_validator(None, DummyField(math.inf))
    with pytest.raises(ValidationError, match='Enter a gain between'):
        forms.IMAGE_ASI676MC_REPAIR__GAIN_validator(None, DummyField(-1.0))
    forms.IMAGE_ASI676MC_REPAIR__GAIN_validator(None, DummyField(1.0))

    # IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator
    with pytest.raises(ValidationError, match='Enter a number'):
        forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Enter a number'):
        forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator(None, DummyField(math.nan))
    with pytest.raises(ValidationError, match='Enter a value greater than 0 and no more than 1'):
        forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator(None, DummyField(0.0))
    with pytest.raises(ValidationError, match='Enter a value greater than 0 and no more than 1'):
        forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator(None, DummyField(1.5))
    forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator(None, DummyField(0.5))

    # IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator
    with pytest.raises(ValidationError, match='Enter a whole number'):
        forms.IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Enter an even number'):
        forms.IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator(None, DummyField(1))
    with pytest.raises(ValidationError, match='Enter an even number'):
        forms.IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator(None, DummyField(3))
    with pytest.raises(ValidationError, match='Enter an even number'):
        forms.IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator(None, DummyField(100000))
    forms.IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator(None, DummyField(32))
