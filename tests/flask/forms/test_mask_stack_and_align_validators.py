import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


def test_image_compression_and_raw():
    # IMAGE_FILE_COMPRESSION__JPG_validator
    with pytest.raises(ValidationError, match='JPEG compression must be 1 or greater'):
        forms.IMAGE_FILE_COMPRESSION__JPG_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='JPEG compression must be 100 or less'):
        forms.IMAGE_FILE_COMPRESSION__JPG_validator(None, DummyField(101))
    forms.IMAGE_FILE_COMPRESSION__JPG_validator(None, DummyField(85))

    # IMAGE_FILE_COMPRESSION__PNG_validator
    with pytest.raises(ValidationError, match='PNG compression must be 1 or greater'):
        forms.IMAGE_FILE_COMPRESSION__PNG_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='PNG compression must be 9 or less'):
        forms.IMAGE_FILE_COMPRESSION__PNG_validator(None, DummyField(10))
    forms.IMAGE_FILE_COMPRESSION__PNG_validator(None, DummyField(6))

    # IMAGE_EXPORT_RAW_validator
    forms.IMAGE_EXPORT_RAW_validator(None, DummyField(''))
    forms.IMAGE_EXPORT_RAW_validator(None, DummyField('png'))
    with pytest.raises(ValidationError, match='Please select a valid file type'):
        forms.IMAGE_EXPORT_RAW_validator(None, DummyField('invalid'))


def test_image_scale_and_circle_mask():
    # IMAGE_SCALE_validator
    with pytest.raises(ValidationError, match='Image Scaling must be 1 or greater'):
        forms.IMAGE_SCALE_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Image Scaling must be 100 or less'):
        forms.IMAGE_SCALE_validator(None, DummyField(101))
    forms.IMAGE_SCALE_validator(None, DummyField(50))

    # IMAGE_CIRCLE_MASK__DIAMETER_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_CIRCLE_MASK__DIAMETER_validator(None, DummyField(100.5))
    with pytest.raises(ValidationError, match='Diameter must be 100 or greater'):
        forms.IMAGE_CIRCLE_MASK__DIAMETER_validator(None, DummyField(50))
    forms.IMAGE_CIRCLE_MASK__DIAMETER_validator(None, DummyField(500))

    # IMAGE_CIRCLE_MASK__OFFSET_X_validator & Y
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_CIRCLE_MASK__OFFSET_X_validator(None, DummyField('abc'))
    forms.IMAGE_CIRCLE_MASK__OFFSET_X_validator(None, DummyField(10))

    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_CIRCLE_MASK__OFFSET_Y_validator(None, DummyField('abc'))
    forms.IMAGE_CIRCLE_MASK__OFFSET_Y_validator(None, DummyField(10))

    # IMAGE_CIRCLE_MASK__BLUR_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_CIRCLE_MASK__BLUR_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Blur must be 0 or more'):
        forms.IMAGE_CIRCLE_MASK__BLUR_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Blur must be an odd number'):
        forms.IMAGE_CIRCLE_MASK__BLUR_validator(None, DummyField(4))
    forms.IMAGE_CIRCLE_MASK__BLUR_validator(None, DummyField(0))
    forms.IMAGE_CIRCLE_MASK__BLUR_validator(None, DummyField(5))

    # IMAGE_CIRCLE_MASK__OPACITY_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_CIRCLE_MASK__OPACITY_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Opacity must be 0 or more'):
        forms.IMAGE_CIRCLE_MASK__OPACITY_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Opacity must be 100 or less'):
        forms.IMAGE_CIRCLE_MASK__OPACITY_validator(None, DummyField(101))
    forms.IMAGE_CIRCLE_MASK__OPACITY_validator(None, DummyField(50))

    # IMAGE_CALIBRATE_MANUAL_OFFSET_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_CALIBRATE_MANUAL_OFFSET_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Offset must be 0 or more'):
        forms.IMAGE_CALIBRATE_MANUAL_OFFSET_validator(None, DummyField(-1))
    forms.IMAGE_CALIBRATE_MANUAL_OFFSET_validator(None, DummyField(10))


def test_fish2pano_validators():
    # FISH2PANO__DIAMETER_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FISH2PANO__DIAMETER_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Diameter must be 100 or greater'):
        forms.FISH2PANO__DIAMETER_validator(None, DummyField(50))
    forms.FISH2PANO__DIAMETER_validator(None, DummyField(500))

    # FISH2PANO__OFFSET_X_validator & Y
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FISH2PANO__OFFSET_X_validator(None, DummyField('abc'))
    forms.FISH2PANO__OFFSET_X_validator(None, DummyField(0))

    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FISH2PANO__OFFSET_Y_validator(None, DummyField('abc'))
    forms.FISH2PANO__OFFSET_Y_validator(None, DummyField(0))

    # FISH2PANO__ROTATE_ANGLE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FISH2PANO__ROTATE_ANGLE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Rotation angle must be -180 or greater'):
        forms.FISH2PANO__ROTATE_ANGLE_validator(None, DummyField(-185.0))
    with pytest.raises(ValidationError, match='Rotation angle must be 180 or less'):
        forms.FISH2PANO__ROTATE_ANGLE_validator(None, DummyField(185.0))
    forms.FISH2PANO__ROTATE_ANGLE_validator(None, DummyField(45.0))

    # FISH2PANO__SCALE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FISH2PANO__SCALE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Scale must be 0.1 or greater'):
        forms.FISH2PANO__SCALE_validator(None, DummyField(0.05))
    with pytest.raises(ValidationError, match='Scale must be 1.0 or less'):
        forms.FISH2PANO__SCALE_validator(None, DummyField(1.5))
    forms.FISH2PANO__SCALE_validator(None, DummyField(0.5))

    # FISH2PANO__MODULUS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.FISH2PANO__MODULUS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Modulus must be 1 or greater'):
        forms.FISH2PANO__MODULUS_validator(None, DummyField(0))
    forms.FISH2PANO__MODULUS_validator(None, DummyField(10))

    # IMAGE_CROP_ROI_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_CROP_ROI_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Crop Region of Interest must be 0 or greater'):
        forms.IMAGE_CROP_ROI_validator(None, DummyField(-1))
    forms.IMAGE_CROP_ROI_validator(None, DummyField(100))


def test_stack_and_align_validators():
    # IMAGE_STACK_METHOD_validator
    forms.IMAGE_STACK_METHOD_validator(None, DummyField('maximum'))
    forms.IMAGE_STACK_METHOD_validator(None, DummyField('average'))
    forms.IMAGE_STACK_METHOD_validator(None, DummyField('minimum'))
    with pytest.raises(ValidationError, match='Invalid selection'):
        forms.IMAGE_STACK_METHOD_validator(None, DummyField('invalid'))

    # IMAGE_STACK_COUNT_validator
    with pytest.raises(ValidationError, match='Invalid data'):
        forms.IMAGE_STACK_COUNT_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Stack count too low'):
        forms.IMAGE_STACK_COUNT_validator(None, DummyField(0))
    forms.IMAGE_STACK_COUNT_validator(None, DummyField(5))

    # IMAGE_ALIGN_DETECTSIGMA_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_ALIGN_DETECTSIGMA_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Detection Sigma must be 3 or greater'):
        forms.IMAGE_ALIGN_DETECTSIGMA_validator(None, DummyField(1))
    with pytest.raises(ValidationError, match='Detection Sigma must be 20 or less'):
        forms.IMAGE_ALIGN_DETECTSIGMA_validator(None, DummyField(21))
    forms.IMAGE_ALIGN_DETECTSIGMA_validator(None, DummyField(5))

    # IMAGE_ALIGN_POINTS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_ALIGN_POINTS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Detection points must be 25 or greater'):
        forms.IMAGE_ALIGN_POINTS_validator(None, DummyField(20))
    with pytest.raises(ValidationError, match='Detection points must be 200 or less'):
        forms.IMAGE_ALIGN_POINTS_validator(None, DummyField(201))
    forms.IMAGE_ALIGN_POINTS_validator(None, DummyField(50))

    # IMAGE_ALIGN_SOURCEMINAREA_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_ALIGN_SOURCEMINAREA_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Source min area must be 3 or greater'):
        forms.IMAGE_ALIGN_SOURCEMINAREA_validator(None, DummyField(2))
    with pytest.raises(ValidationError, match='Source min area must be 25 or less'):
        forms.IMAGE_ALIGN_SOURCEMINAREA_validator(None, DummyField(26))
    forms.IMAGE_ALIGN_SOURCEMINAREA_validator(None, DummyField(5))


def test_expire_and_framerate_validators():
    # IMAGE_EXPIRE_DAYS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_EXPIRE_DAYS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Image Expiration must be 1 or greater'):
        forms.IMAGE_EXPIRE_DAYS_validator(None, DummyField(0))
    forms.IMAGE_EXPIRE_DAYS_validator(None, DummyField(30))

    # TIMELAPSE_EXPIRE_DAYS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.TIMELAPSE_EXPIRE_DAYS_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Timelapse Expiration must be 1 or greater'):
        forms.TIMELAPSE_EXPIRE_DAYS_validator(None, DummyField(0))
    forms.TIMELAPSE_EXPIRE_DAYS_validator(None, DummyField(30))

    # FFMPEG_FRAMERATE_validator
    with pytest.raises(ValidationError, match='FFMPEG frame rate must be 10 or greater'):
        forms.FFMPEG_FRAMERATE_validator(None, DummyField(9))
    with pytest.raises(ValidationError, match='FFMPEG frame rate must be 60 or less'):
        forms.FFMPEG_FRAMERATE_validator(None, DummyField(61))
    forms.FFMPEG_FRAMERATE_validator(None, DummyField(25))
