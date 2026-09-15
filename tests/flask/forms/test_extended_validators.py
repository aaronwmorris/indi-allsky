from unittest.mock import MagicMock
import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms as f_mod


class DummyField:
    def __init__(self, data):
        self.data = data


class DummyForm:
    def __init__(self):
        self.CAMERA_INTERFACE_choices = {
            'INDI': [('indi_simulator_ccd', 'INDI Simulator CCD')],
            'libcamera': [('libcamera', 'libcamera')],
        }


# ==============================================================================
# Standalone Validator Tests
# ==============================================================================

def test_uri_validator():
    f_mod.SQLALCHEMY_DATABASE_URI_validator(DummyForm(), DummyField("sqlite:////tmp/test.db"))
    f_mod.SQLALCHEMY_DATABASE_URI_validator(DummyForm(), DummyField("postgresql://user:pass@localhost:5432/db"))
    with pytest.raises(ValidationError):
        f_mod.SQLALCHEMY_DATABASE_URI_validator(DummyForm(), DummyField("invalid uri with spaces!"))


def test_camera_interface_validator():
    form = DummyForm()
    f_mod.CAMERA_INTERFACE_validator(form, DummyField("indi_simulator_ccd"))
    f_mod.CAMERA_INTERFACE_validator(form, DummyField("libcamera"))
    with pytest.raises(ValidationError):
        f_mod.CAMERA_INTERFACE_validator(form, DummyField("unknown_interface"))


def test_indi_server_and_port_validator():
    f_mod.INDI_SERVER_validator(DummyForm(), DummyField(""))
    f_mod.INDI_SERVER_validator(DummyForm(), DummyField("localhost"))
    f_mod.INDI_SERVER_validator(DummyForm(), DummyField("192.168.1.100"))
    f_mod.INDI_SERVER_validator(DummyForm(), DummyField("indi_host-1"))
    with pytest.raises(ValidationError):
        f_mod.INDI_SERVER_validator(DummyForm(), DummyField("invalid server name!#$"))

    f_mod.INDI_PORT_validator(DummyForm(), DummyField(7624))
    with pytest.raises(ValidationError):
        f_mod.INDI_PORT_validator(DummyForm(), DummyField("not-an-int"))
    with pytest.raises(ValidationError):
        f_mod.INDI_PORT_validator(DummyForm(), DummyField(-1))
    with pytest.raises(ValidationError):
        f_mod.INDI_PORT_validator(DummyForm(), DummyField(70000))


def test_lens_validators():
    f_mod.OWNER_validator(DummyForm(), DummyField(""))
    f_mod.OWNER_validator(DummyForm(), DummyField("John Doe_123"))
    with pytest.raises(ValidationError):
        f_mod.OWNER_validator(DummyForm(), DummyField("John <Bad>"))

    f_mod.LENS_FOCAL_LENGTH_validator(DummyForm(), DummyField(2.5))
    with pytest.raises(ValidationError):
        f_mod.LENS_FOCAL_LENGTH_validator(DummyForm(), DummyField("str"))
    with pytest.raises(ValidationError):
        f_mod.LENS_FOCAL_LENGTH_validator(DummyForm(), DummyField(0.0))

    f_mod.LENS_FOCAL_RATIO_validator(DummyForm(), DummyField(1.4))
    with pytest.raises(ValidationError):
        f_mod.LENS_FOCAL_RATIO_validator(DummyForm(), DummyField("str"))
    with pytest.raises(ValidationError):
        f_mod.LENS_FOCAL_RATIO_validator(DummyForm(), DummyField(-0.5))

    f_mod.LENS_IMAGE_CIRCLE_validator(DummyForm(), DummyField(100))
    with pytest.raises(ValidationError):
        f_mod.LENS_IMAGE_CIRCLE_validator(DummyForm(), DummyField(-5))

    f_mod.LENS_ALTITUDE_validator(DummyForm(), DummyField(45.0))
    with pytest.raises(ValidationError):
        f_mod.LENS_ALTITUDE_validator(DummyForm(), DummyField(95.0))
    with pytest.raises(ValidationError):
        f_mod.LENS_ALTITUDE_validator(DummyForm(), DummyField(-1.0))

    f_mod.LENS_AZIMUTH_validator(DummyForm(), DummyField(180.0))
    with pytest.raises(ValidationError):
        f_mod.LENS_AZIMUTH_validator(DummyForm(), DummyField(365.0))
    with pytest.raises(ValidationError):
        f_mod.LENS_AZIMUTH_validator(DummyForm(), DummyField(-1.0))


def test_ccd_validators():
    f_mod.CCD_GAIN_validator(DummyForm(), DummyField(100))
    with pytest.raises(ValidationError):
        f_mod.CCD_GAIN_validator(DummyForm(), DummyField(-1))

    f_mod.CCD_BINNING_validator(DummyForm(), DummyField(1))
    f_mod.CCD_BINNING_validator(DummyForm(), DummyField(2))
    with pytest.raises(ValidationError):
        f_mod.CCD_BINNING_validator(DummyForm(), DummyField(5))
    with pytest.raises(ValidationError):
        f_mod.CCD_BINNING_validator(DummyForm(), DummyField(0))

    f_mod.CCD_EXPOSURE_validator(DummyForm(), DummyField(10.0))
    f_mod.CCD_EXPOSURE_validator(DummyForm(), DummyField(0.0))
    with pytest.raises(ValidationError):
        f_mod.CCD_EXPOSURE_validator(DummyForm(), DummyField(-1.0))
    with pytest.raises(ValidationError):
        f_mod.CCD_EXPOSURE_validator(DummyForm(), DummyField("abc"))

    f_mod.CAMERA_SQM__EXPOSURE_validator(DummyForm(), DummyField(5.0))
    with pytest.raises(ValidationError):
        f_mod.CAMERA_SQM__EXPOSURE_validator(DummyForm(), DummyField(-1.0))

    f_mod.CCD_EXPOSURE_TIMEOUT_validator(DummyForm(), DummyField(180))
    with pytest.raises(ValidationError):
        f_mod.CCD_EXPOSURE_TIMEOUT_validator(DummyForm(), DummyField(30))
    with pytest.raises(ValidationError):
        f_mod.CCD_EXPOSURE_TIMEOUT_validator(DummyForm(), DummyField(-5))

    f_mod.EXPOSURE_PERIOD_validator(DummyForm(), DummyField(60))
    with pytest.raises(ValidationError):
        f_mod.EXPOSURE_PERIOD_validator(DummyForm(), DummyField(-1))

    f_mod.EXPOSURE_PERIOD_DAY_validator(DummyForm(), DummyField(60))
    with pytest.raises(ValidationError):
        f_mod.EXPOSURE_PERIOD_DAY_validator(DummyForm(), DummyField(-1))

    f_mod.CAMERA_SQM__EXPOSURE_PERIOD_validator(DummyForm(), DummyField(120))
    with pytest.raises(ValidationError):
        f_mod.CAMERA_SQM__EXPOSURE_PERIOD_validator(DummyForm(), DummyField(-1))

    f_mod.SQM_MAGNITUDE_OFFSET_validator(DummyForm(), DummyField(20.5))
    with pytest.raises(ValidationError):
        f_mod.SQM_MAGNITUDE_OFFSET_validator(DummyForm(), DummyField("abc"))


def test_image_processing_validators():
    f_mod.TIMELAPSE_SKIP_FRAMES_validator(DummyForm(), DummyField(0))
    with pytest.raises(ValidationError):
        f_mod.TIMELAPSE_SKIP_FRAMES_validator(DummyForm(), DummyField(-1))

    f_mod.TIMELAPSE__IMAGE_CIRCLE_validator(DummyForm(), DummyField(100))
    with pytest.raises(ValidationError):
        f_mod.TIMELAPSE__IMAGE_CIRCLE_validator(DummyForm(), DummyField(-1))

    f_mod.TIMELAPSE__KEOGRAM_RATIO_validator(DummyForm(), DummyField(0.1))
    with pytest.raises(ValidationError):
        f_mod.TIMELAPSE__KEOGRAM_RATIO_validator(DummyForm(), DummyField(0.005))
    with pytest.raises(ValidationError):
        f_mod.TIMELAPSE__KEOGRAM_RATIO_validator(DummyForm(), DummyField(0.5))

    f_mod.TIMELAPSE__PRE_SCALE_validator(DummyForm(), DummyField(1.0))
    with pytest.raises(ValidationError):
        f_mod.TIMELAPSE__PRE_SCALE_validator(DummyForm(), DummyField(0.0))

    f_mod.CCD_TEMP_validator(DummyForm(), DummyField(-10.0))
    with pytest.raises(ValidationError):
        f_mod.CCD_TEMP_validator(DummyForm(), DummyField("str"))

    f_mod.FOCUS_DELAY_validator(DummyForm(), DummyField(5))
    with pytest.raises(ValidationError):
        f_mod.FOCUS_DELAY_validator(DummyForm(), DummyField(-1))

    f_mod.WB_FACTOR_validator(DummyForm(), DummyField(1.5))
    with pytest.raises(ValidationError):
        f_mod.WB_FACTOR_validator(DummyForm(), DummyField(-0.5))

    f_mod.WB_MTF_MIDTONES_validator(DummyForm(), DummyField(0.5))
    with pytest.raises(ValidationError):
        f_mod.WB_MTF_MIDTONES_validator(DummyForm(), DummyField(1.2))

    f_mod.SATURATION_FACTOR_validator(DummyForm(), DummyField(1.2))
    with pytest.raises(ValidationError):
        f_mod.SATURATION_FACTOR_validator(DummyForm(), DummyField(-1.0))

    f_mod.GAMMA_CORRECTION_validator(DummyForm(), DummyField(1.0))
    with pytest.raises(ValidationError):
        f_mod.GAMMA_CORRECTION_validator(DummyForm(), DummyField(0.0))

    f_mod.SHARPEN_AMOUNT_validator(DummyForm(), DummyField(1.5))
    with pytest.raises(ValidationError):
        f_mod.SHARPEN_AMOUNT_validator(DummyForm(), DummyField(-0.1))

    f_mod.SCNR_MTF_MIDTONES_validator(DummyForm(), DummyField(0.5))
    with pytest.raises(ValidationError):
        f_mod.SCNR_MTF_MIDTONES_validator(DummyForm(), DummyField(2.0))

    f_mod.IMAGE_DENOISE_STRENGTH_validator(DummyForm(), DummyField(5.0))
    with pytest.raises(ValidationError):
        f_mod.IMAGE_DENOISE_STRENGTH_validator(DummyForm(), DummyField(-1.0))

    f_mod.BILATERAL_SIGMA_validator(DummyForm(), DummyField(10.0))
    with pytest.raises(ValidationError):
        f_mod.BILATERAL_SIGMA_validator(DummyForm(), DummyField(-1.0))


# ==============================================================================
# Form Initialization & Choices Population Tests
# ==============================================================================

def test_user_info_form(flask_app):
    with flask_app.test_request_context():
        form = f_mod.IndiAllskyUserInfoForm(data={
            'NAME': 'Test User',
            'EMAIL': 'user@example.com',
        })
        assert form.NAME.data == 'Test User'


def test_set_date_time_and_tz_forms(flask_app):
    with flask_app.test_request_context():
        dt_form = f_mod.IndiAllskySetDateTimeForm(data={'NEW_DATETIME': '2026-09-06T12:00:00'})
        assert dt_form.NEW_DATETIME is not None

        tz_form = f_mod.IndiAllskySetTimezoneForm()
        assert len(tz_form.NEW_TIMEZONE.choices) > 0


def test_system_info_and_history_forms(flask_app):
    with flask_app.test_request_context():
        sys_form = f_mod.IndiAllskySystemInfoForm(data={
            'CAMERA_ID': '1',
            'SERVICE_HIDDEN': 'indi-allsky',
            'COMMAND_HIDDEN': 'restart',
        })
        assert sys_form.CAMERA_ID.data == '1'

        loop_form = f_mod.IndiAllskyLoopHistoryForm(data={'HISTORY_SELECT': '1800'})
        assert loop_form.HISTORY_SELECT.data == '1800'

        chart_form = f_mod.IndiAllskyChartHistoryForm(data={'HISTORY_SELECT': '3600'})
        assert chart_form.HISTORY_SELECT.data == '3600'


def test_image_exclude_and_focus_forms(flask_app):
    with flask_app.test_request_context():
        exclude_form = f_mod.IndiAllskyImageExcludeForm(data={
            'EXCLUDE_IMAGE_ID': '123',
            'EXCLUDE_EXCLUDE': True,
        })
        assert exclude_form.EXCLUDE_IMAGE_ID.data == '123'

        focus_form = f_mod.IndiAllskyFocusForm(data={'ZOOM_SELECT': '5'})
        assert focus_form.ZOOM_SELECT.data == '5'

        focus_ctrl_form = f_mod.IndiAllskyFocusControllerForm(data={'DIRECTION': 'in', 'STEP_DEGREES': 12})
        assert focus_ctrl_form.DIRECTION.data == 'in'


def test_mini_timelapse_and_longterm_keogram_forms(flask_app):
    with flask_app.test_request_context():
        mt_form = f_mod.IndiAllskyMiniTimelapseForm(data={
            'CAMERA_ID': '1',
            'IMAGE_ID': '10',
            'PRE_SECONDS_SELECT': '300',
            'POST_SECONDS_SELECT': '300',
            'FRAMERATE_SELECT': '25',
            'BITRATE_SELECT': '10000k',
            'NOTE': 'test note',
        })
        assert mt_form.NOTE.data == 'test note'

        ltk_form = f_mod.IndiAllskyLongTermKeogramForm()
        assert len(ltk_form.DAYS_SELECT_choices) > 0


def test_helpers_and_simulator_forms(flask_app):
    with flask_app.test_request_context():
        circle_form = f_mod.IndiAllskyImageCircleHelperForm(data={'IMAGE_CIRCLE_DIAMETER': 500})
        assert circle_form.IMAGE_CIRCLE_DIAMETER.data == 500

        sky_form = f_mod.IndiAllskyVirtualSkyHelperForm(data={'AZIMUTH_ANGLE': 180.0})
        assert sky_form.AZIMUTH_ANGLE.data == 180.0

        server_form = f_mod.IndiAllskyIndiServerChangeForm(data={'RESTART_INDISERVER': True})
        assert server_form.RESTART_INDISERVER.data is True

        sim_form = f_mod.IndiAllskyCameraSimulatorForm()
        assert len(sim_form.SENSOR_SELECT_choices) > 0


def test_asi676mc_calibration_form(flask_app):
    with flask_app.test_request_context():
        cal_form = f_mod.IndiAllskyAsi676mcCalibrationForm(data={
            'CAMERA_ID': 1,
            'MAX_PAIR_SECONDS': 60.0,
            'DATABASE_GROUP_LIMIT': 10,
        })
        assert cal_form.MAX_PAIR_SECONDS.data == 60.0
        assert cal_form.DATABASE_GROUP_LIMIT.data == 10


def test_config_form_init(flask_app, base_config):
    with flask_app.test_request_context():
        data = dict(base_config)
        for slot in ['A', 'B', 'C', 'D', 'E', 'F']:
            data[f'TEMP_SENSOR__{slot}_CLASSNAME'] = 'None'
            data[f'TEMP_SENSOR__{slot}_LABEL'] = f'Sensor {slot}'
            data[f'TEMP_SENSOR__{slot}_USER_VAR_SLOT'] = 'None'
            data[f'TEMP_SENSOR__{slot}_PIN_1'] = 'None'
        form = f_mod.IndiAllskyConfigForm(data=data)
        assert form is not None
        assert form.CAMERA_INTERFACE is not None
        assert form.INDI_SERVER is not None

