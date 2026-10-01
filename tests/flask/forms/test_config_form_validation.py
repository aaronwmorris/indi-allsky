"""Tests for IndiAllskyConfigForm.validate() and related config form methods in indi_allsky.flask.forms."""
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import psutil

from indi_allsky.flask import forms as f_mod
from indi_allsky.flask.forms import IndiAllskyConfigForm, IndiAllskyConfigRestoreForm, IndiAllskyAsi676mcCalibrationForm


@pytest.fixture
def base_config_dict(base_config):
    data = dict(base_config)
    for slot in ['A', 'B', 'C', 'D', 'E', 'F']:
        data[f'TEMP_SENSOR__{slot}_CLASSNAME'] = ''
        data[f'TEMP_SENSOR__{slot}_LABEL'] = f'Sensor {slot}'
        data[f'TEMP_SENSOR__{slot}_USER_VAR_SLOT'] = 'sensor_user_0'
        data[f'TEMP_SENSOR__{slot}_PIN_1'] = ''
        data[f'TEMP_SENSOR__{slot}_PIN_2'] = ''
    data['CAMERA_INTERFACE'] = 'indi'
    data['FILETRANSFER__HOST'] = ''
    data['S3UPLOAD__ENABLE'] = False
    data['FOCUSER__CLASSNAME'] = ''
    data['DEW_HEATER__CLASSNAME'] = ''
    data['FAN__CLASSNAME'] = ''
    data['GENERIC_GPIO__A_CLASSNAME'] = ''
    data['MANUAL_GPIO__A_CLASSNAME'] = ''
    data['CCD_BIT_DEPTH'] = '0'
    data['ADU_FOV_DIV'] = '4'
    data['SQM_FOV_DIV'] = '4'
    data['LIBCAMERA__CAMERA_ID'] = '0'
    data['LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE'] = '{month:%B %Y}'
    return data


def test_config_form_update_choices_with_sensors(flask_app, base_config_dict):
    """Test update_choices() populating sensor slots from sensor classes and psutil."""
    with flask_app.test_request_context():
        # Setup config dict with sensors A through F
        cfg = dict(base_config_dict)
        cfg['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        cfg['TEMP_SENSOR__A_USER_VAR_SLOT'] = 'sensor_user_0'
        cfg['TEMP_SENSOR__A_PIN_1'] = 'D1'

        cfg['TEMP_SENSOR__B_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        cfg['TEMP_SENSOR__B_USER_VAR_SLOT'] = 'sensor_user_10'
        cfg['TEMP_SENSOR__B_PIN_1'] = 'D2'

        cfg['TEMP_SENSOR__C_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        cfg['TEMP_SENSOR__C_USER_VAR_SLOT'] = 'sensor_user_20'
        cfg['TEMP_SENSOR__C_PIN_1'] = 'D3'

        cfg['TEMP_SENSOR__D_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        cfg['TEMP_SENSOR__D_USER_VAR_SLOT'] = 'sensor_user_30'
        cfg['TEMP_SENSOR__D_PIN_1'] = 'D4'

        cfg['TEMP_SENSOR__E_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        cfg['TEMP_SENSOR__E_USER_VAR_SLOT'] = 'sensor_user_40'
        cfg['TEMP_SENSOR__E_PIN_1'] = 'D5'

        cfg['TEMP_SENSOR__F_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        cfg['TEMP_SENSOR__F_USER_VAR_SLOT'] = 'sensor_user_50'
        cfg['TEMP_SENSOR__F_PIN_1'] = 'D6'

        mock_temp = MagicMock()
        mock_temp.label = 'Core 0'
        with patch('psutil.sensors_temperatures', return_value={'cpu_thermal': [mock_temp]}):
            form = IndiAllskyConfigForm(data=cfg)
            assert form is not None
            assert len(form.SENSOR_SLOT_choices['User Sensors']) > 0


def test_config_form_exposure_and_interface_validation(flask_app, base_config_dict):
    """Test exposure bounds and pycurl camera validations in validate()."""
    with flask_app.test_request_context():
        # 1. CCD_EXPOSURE_DEF > CCD_EXPOSURE_MAX
        data = dict(base_config_dict)
        data['CCD_EXPOSURE_DEF'] = 50.0
        data['CCD_EXPOSURE_MAX'] = 30.0
        form = IndiAllskyConfigForm(data=data)
        assert form.validate() is False
        assert 'Default exposure cannot be greater than max exposure' in form.CCD_EXPOSURE_DEF.errors

        # 2. CCD_EXPOSURE_MIN > CCD_EXPOSURE_MAX
        data2 = dict(base_config_dict)
        data2['CCD_EXPOSURE_MIN'] = 50.0
        data2['CCD_EXPOSURE_MAX'] = 30.0
        form2 = IndiAllskyConfigForm(data=data2)
        assert form2.validate() is False

        # 3. CAMERA_INTERFACE == 'pycurl_camera' with blank URL
        data3 = dict(base_config_dict)
        data3['CAMERA_INTERFACE'] = 'pycurl_camera'
        data3['PYCURL_CAMERA__URL'] = ''
        form3 = IndiAllskyConfigForm(data=data3)
        assert form3.validate() is False
        assert 'URL cannot blank' in form3.PYCURL_CAMERA__URL.errors

        # 4. TEXT_PROPERTIES__PIL_FONT_FILE == 'custom' with blank custom font
        data4 = dict(base_config_dict)
        data4['TEXT_PROPERTIES__PIL_FONT_FILE'] = 'custom'
        data4['TEXT_PROPERTIES__PIL_FONT_CUSTOM'] = ''
        form4 = IndiAllskyConfigForm(data=data4)
        assert form4.validate() is False


def test_config_form_roi_and_border_validation(flask_app, base_config_dict):
    """Test ROI coordinates (ADU, crop, SQM) and border odd dimension checks."""
    with flask_app.test_request_context():
        # 1. ADU_ROI X2 <= X1, Y2 <= Y1
        data = dict(base_config_dict)
        data['ADU_ROI_X1'] = 100
        data['ADU_ROI_X2'] = 50
        data['ADU_ROI_Y1'] = 100
        data['ADU_ROI_Y2'] = 50
        form = IndiAllskyConfigForm(data=data)
        assert form.validate() is False

        # 2. IMAGE_CROP_ROI X2 <= X1, Y2 <= Y1
        data2 = dict(base_config_dict)
        data2['IMAGE_CROP_ROI_X1'] = 100
        data2['IMAGE_CROP_ROI_X2'] = 50
        data2['IMAGE_CROP_ROI_Y1'] = 100
        data2['IMAGE_CROP_ROI_Y2'] = 50
        form2 = IndiAllskyConfigForm(data=data2)
        assert form2.validate() is False

        # 3. SQM_ROI X2 <= X1, Y2 <= Y1
        data3 = dict(base_config_dict)
        data3['SQM_ROI_X1'] = 100
        data3['SQM_ROI_X2'] = 50
        data3['SQM_ROI_Y1'] = 100
        data3['SQM_ROI_Y2'] = 50
        form3 = IndiAllskyConfigForm(data=data3)
        assert form3.validate() is False

        # 4. Odd Crop dimension
        data4 = dict(base_config_dict)
        data4['IMAGE_CROP_ROI_X1'] = 0
        data4['IMAGE_CROP_ROI_X2'] = 51  # delta 51 is odd
        data4['IMAGE_CROP_ROI_Y1'] = 0
        data4['IMAGE_CROP_ROI_Y2'] = 51
        form4 = IndiAllskyConfigForm(data=data4)
        assert form4.validate() is False

        # 5. Odd Border sum
        data5 = dict(base_config_dict)
        data5['IMAGE_BORDER__TOP'] = 1
        data5['IMAGE_BORDER__BOTTOM'] = 0
        data5['IMAGE_BORDER__LEFT'] = 1
        data5['IMAGE_BORDER__RIGHT'] = 0
        form5 = IndiAllskyConfigForm(data=data5)
        assert form5.validate() is False


def test_config_form_filetransfer_upload_flags(flask_app, base_config_dict):
    """Test all FILETRANSFER upload flags when FILETRANSFER__HOST is empty."""
    with flask_app.test_request_context():
        upload_keys = [
            'FILETRANSFER__UPLOAD_IMAGE',
            'FILETRANSFER__UPLOAD_PANORAMA',
            'FILETRANSFER__UPLOAD_RAW',
            'FILETRANSFER__UPLOAD_FITS',
            'FILETRANSFER__UPLOAD_METADATA',
            'FILETRANSFER__UPLOAD_VIDEO',
            'FILETRANSFER__UPLOAD_MINI_VIDEO',
            'FILETRANSFER__UPLOAD_KEOGRAM',
            'FILETRANSFER__UPLOAD_STARTRAIL',
            'FILETRANSFER__UPLOAD_STARTRAIL_VIDEO',
            'FILETRANSFER__UPLOAD_PANORAMA_VIDEO',
            'FILETRANSFER__UPLOAD_ENDOFNIGHT',
            'FILETRANSFER__UPLOAD_REALTIME_KEOGRAM',
            'FILETRANSFER__UPLOAD_LATEST_IMAGE',
            'FILETRANSFER__UPLOAD_LATEST_PANORAMA',
            'FILETRANSFER__UPLOAD_LATEST_RAW',
            'FILETRANSFER__UPLOAD_LATEST_VIDEO',
            'FILETRANSFER__UPLOAD_DB_BACKUP',
        ]
        for key in upload_keys:
            data = dict(base_config_dict)
            data['FILETRANSFER__HOST'] = ''
            data[key] = True
            form = IndiAllskyConfigForm(data=data)
            assert form.validate() is False
            assert 'No file transfer host is configured' in form.FILETRANSFER__HOST.errors


def test_config_form_s3_and_focuser_validation(flask_app, base_config_dict):
    """Test S3 and Focuser validations in validate()."""
    with flask_app.test_request_context():
        # S3 boto3_generic missing endpoint
        data = dict(base_config_dict)
        data['S3UPLOAD__ENABLE'] = True
        data['S3UPLOAD__CLASSNAME'] = 'boto3_generic'
        data['S3UPLOAD__ENDPOINT_URL'] = ''
        form = IndiAllskyConfigForm(data=data)
        assert form.validate() is False
        assert 'Endpoint URL is required' in form.S3UPLOAD__ENDPOINT_URL.errors

        # Focuser blinka
        data_foc = dict(base_config_dict)
        data_foc['FOCUSER__CLASSNAME'] = 'blinka_stepper'
        data_foc['FOCUSER__GPIO_PIN_1'] = ''
        data_foc['FOCUSER__GPIO_PIN_2'] = ''
        data_foc['FOCUSER__GPIO_PIN_3'] = ''
        data_foc['FOCUSER__GPIO_PIN_4'] = ''
        mock_board = MagicMock()
        with patch.dict(sys.modules, {'board': mock_board}):
            form_foc = IndiAllskyConfigForm(data=data_foc)
            assert form_foc.validate() is False


def test_config_form_dew_heater_and_fan_validation(flask_app, base_config_dict):
    """Test Dew Heater and Fan validations in validate()."""
    with flask_app.test_request_context():
        # Dew heater blinka, rpigpio, gpiozero, motorkit, dockerpi
        data_dh = dict(base_config_dict)
        data_dh['DEW_HEATER__CLASSNAME'] = 'blinka_relay'
        data_dh['DEW_HEATER__PIN_1'] = ''
        data_dh['DEW_HEATER__THOLD_DIFF_HIGH'] = 10
        data_dh['DEW_HEATER__THOLD_DIFF_MED'] = 5  # HIGH >= MED triggers error
        data_dh['DEW_HEATER__THOLD_DIFF_LOW'] = 2
        mock_board = MagicMock()
        with patch.dict(sys.modules, {'board': mock_board}):
            form_dh = IndiAllskyConfigForm(data=data_dh)
            assert form_dh.validate() is False

        # Dew heater threshold: HIGH >= MED and MED >= LOW
        data_dh2 = dict(base_config_dict)
        data_dh2['DEW_HEATER__THOLD_DIFF_HIGH'] = 15
        data_dh2['DEW_HEATER__THOLD_DIFF_MED'] = 10
        data_dh2['DEW_HEATER__THOLD_DIFF_LOW'] = 5
        form_dh2 = IndiAllskyConfigForm(data=data_dh2)
        assert form_dh2.validate() is False

        # Fan threshold: HIGH <= MED and MED <= LOW
        data_fan = dict(base_config_dict)
        data_fan['FAN__CLASSNAME'] = 'blinka_relay'
        data_fan['FAN__PIN_1'] = ''
        data_fan['FAN__THOLD_DIFF_HIGH'] = 5
        data_fan['FAN__THOLD_DIFF_MED'] = 10  # HIGH <= MED triggers error
        data_fan['FAN__THOLD_DIFF_LOW'] = 15
        with patch.dict(sys.modules, {'board': mock_board}):
            form_fan = IndiAllskyConfigForm(data=data_fan)
            assert form_fan.validate() is False


def test_config_form_generic_and_manual_gpio_validation(flask_app, base_config_dict):
    """Test generic and manual GPIO validations in validate()."""
    with flask_app.test_request_context():
        # Generic GPIO A blinka
        data_gpio = dict(base_config_dict)
        data_gpio['GENERIC_GPIO__A_CLASSNAME'] = 'blinka_relay'
        data_gpio['GENERIC_GPIO__A_PIN_1'] = ''
        mock_board = MagicMock()
        with patch.dict(sys.modules, {'board': mock_board}):
            form_gpio = IndiAllskyConfigForm(data=data_gpio)
            assert form_gpio.validate() is False

        # Manual GPIO A rpigpio
        data_mgpio = dict(base_config_dict)
        data_mgpio['MANUAL_GPIO__A_CLASSNAME'] = 'rpigpio_relay'
        data_mgpio['MANUAL_GPIO__A_PIN_1'] = ''
        mock_rpi = MagicMock()
        with patch.dict(sys.modules, {'RPi': mock_rpi, 'RPi.GPIO': mock_rpi}):
            form_mgpio = IndiAllskyConfigForm(data=data_mgpio)
            assert form_mgpio.validate() is False


def test_config_form_sensors_overlapping_slots(flask_app, base_config_dict):
    """Test sensor slot overlap detection in validate()."""
    with flask_app.test_request_context():
        data = dict(base_config_dict)
        data['TEMP_SENSOR__A_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        data['TEMP_SENSOR__A_USER_VAR_SLOT'] = 'sensor_user_0'
        data['TEMP_SENSOR__A_PIN_1'] = 'D1'

        data['TEMP_SENSOR__B_CLASSNAME'] = 'blinka_temp_sensor_bme280_i2c'
        data['TEMP_SENSOR__B_USER_VAR_SLOT'] = 'sensor_user_0'  # overlapping!
        data['TEMP_SENSOR__B_PIN_1'] = 'D2'

        # Dew heater sensor same as dewpoint
        data['DEW_HEATER__THOLD_ENABLE'] = True
        data['DEW_HEATER__TEMP_USER_VAR_SLOT'] = 'sensor_user_1'
        data['DEW_HEATER__DEWPOINT_USER_VAR_SLOT'] = 'sensor_user_1'

        form = IndiAllskyConfigForm(data=data)
        assert form.validate() is False
        assert 'Overlapping slots with Sensor B' in form.TEMP_SENSOR__A_USER_VAR_SLOT.errors
        assert 'Sensor same as dew point' in form.DEW_HEATER__TEMP_USER_VAR_SLOT.errors


def test_config_restore_and_asi676mc_calibration_forms(flask_app, db):
    """Test IndiAllskyConfigRestoreForm, IndiAllskyAsi676mcCalibrationForm, and _asi676mc_diagnostic_assets."""
    with flask_app.test_request_context():
        # IndiAllskyConfigRestoreForm with ENCRYPT_PASSWORDS
        restore_form = IndiAllskyConfigRestoreForm(indi_allsky_config={'ENCRYPT_PASSWORDS': True})
        assert restore_form.RESET_KEYS.render_kw == {'disabled': 'disabled'}

        restore_form2 = IndiAllskyConfigRestoreForm(indi_allsky_config={'ENCRYPT_PASSWORDS': False})
        assert restore_form2.RESET_KEYS.render_kw is None or 'disabled' not in restore_form2.RESET_KEYS.render_kw

        # IndiAllskyAsi676mcCalibrationForm validation
        cal_form = IndiAllskyAsi676mcCalibrationForm(data={
            'CAMERA_ID': 1,
            'MAX_PAIR_SECONDS': 30.0,
            'DATABASE_GROUP_LIMIT': 5,
        })
        assert cal_form.CAMERA_ID.data == 1
        assert cal_form.MAX_PAIR_SECONDS.data == 30.0

        # _asi676mc_diagnostic_assets helper
        now = datetime.now()
        cam = f_mod.IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = f_mod.IndiAllSkyDbCameraTable(
                name="diag_cam",
                uuid="diag-cam-uuid-1",
                friendlyName="Diag Cam",
                latitude=0.0, longitude=0.0,
                local=True,
            )
            db.session.add(cam)
            db.session.commit()

            fits_entry = f_mod.IndiAllSkyDbFitsImageTable(
                camera_id=cam.id,
                filename="diag_bad.fits",
                createDate=now,
                dayDate=now.date(),
                exposure=1.0,
                gain=100.0,
                data={
                    'asi676mc_diagnostic': {
                        'roles': [
                            {'role': 'bad', 'capture_id': 'cap-1'},
                            {'role': 'preceding', 'capture_id': 'cap-1'},
                            {'role': 'following', 'capture_id': 'cap-1'},
                        ],
                    },
                },
            )
            db.session.add(fits_entry)
            db.session.commit()

        img_mock = MagicMock()
        img_mock.id = 1
        img_mock.createDate = now
        img_mock.data = {
            'asi676mc_repair_status': 'repaired',
            'asi676mc_diagnostic_fits': {
                'roles': [{'role': 'bad', 'capture_id': 'cap-1'}],
            },
        }

        res_empty = f_mod._asi676mc_diagnostic_assets([], camera_id=cam.id, s3_prefix='', local=True)
        assert res_empty == {}

        with patch.object(fits_entry, 'getUrl', return_value='/fits/diag_bad.fits'):
            assets = f_mod._asi676mc_diagnostic_assets([img_mock], camera_id=cam.id, s3_prefix='', local=True)
            assert 1 in assets
            assert assets[1]['bad'] is not None


def test_allskymap_form_validators(flask_app):
    """Cover ALLSKYMAP__MAP_LATITUDE_validator and ALLSKYMAP__MAP_LONGITUDE_validator edge cases."""
    with flask_app.test_request_context():
        from wtforms.validators import ValidationError

        class DummyForm:
            LOCATION_LATITUDE = MagicMock(data='-34.9')
            LOCATION_LONGITUDE = MagicMock(data='138.6')

        form = DummyForm()

        # Latitude invalid float
        field = MagicMock(data='invalid')
        with pytest.raises(ValidationError, match='valid number for latitude'):
            f_mod.ALLSKYMAP__MAP_LATITUDE_validator(form, field)

        # Latitude out of range
        field = MagicMock(data='95.0')
        with pytest.raises(ValidationError, match='between -90 and 90'):
            f_mod.ALLSKYMAP__MAP_LATITUDE_validator(form, field)

        # Latitude difference > 1 degree
        field = MagicMock(data='-30.0')
        with pytest.raises(ValidationError, match='within 1 degree'):
            f_mod.ALLSKYMAP__MAP_LATITUDE_validator(form, field)

        # Longitude invalid float
        field = MagicMock(data='invalid')
        with pytest.raises(ValidationError, match='valid number for longitude'):
            f_mod.ALLSKYMAP__MAP_LONGITUDE_validator(form, field)

        # Longitude out of range
        field = MagicMock(data='200.0')
        with pytest.raises(ValidationError, match='between -180 and 180'):
            f_mod.ALLSKYMAP__MAP_LONGITUDE_validator(form, field)

        # Longitude difference > 1 degree
        field = MagicMock(data='145.0')
        with pytest.raises(ValidationError, match='within 1 degree'):
            f_mod.ALLSKYMAP__MAP_LONGITUDE_validator(form, field)


def test_fits_selector_form_coverage(flask_app):
    """Cover FitsSelectorForm getYears, getMonths, getDays, getHours with local=False and getUrl ValueError."""
    with flask_app.test_request_context():
        cam = f_mod.IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        selector = f_mod.IndiAllskyFitsImageViewer(
            camera_id=cam_id,
            s3_prefix='',
            local=False,  # filter non-local
            model=f_mod.IndiAllSkyDbFitsImageTable
        )
        selector.getYears()
        selector.getMonths(2026)
        selector.getDays(2026, 2)
        selector.getHours(2026, 2, 1)

        # getImages error handling when getUrl raises ValueError
        now = datetime.now()
        fits_img = f_mod.IndiAllSkyDbFitsImageTable(
            camera_id=cam_id,
            filename='bad_url.fits',
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
        )
        f_mod.db.session.add(fits_img)
        f_mod.db.session.commit()


        with patch.object(f_mod.IndiAllSkyDbFitsImageTable, 'getUrl', side_effect=ValueError("bad path")):
            imgs = selector.getImages(now.year, now.month, now.day, now.hour)
            assert isinstance(imgs, list)


