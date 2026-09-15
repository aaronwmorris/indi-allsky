import pytest
from wtforms.validators import ValidationError

from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


def test_ffmpeg_and_text_properties():
    # FFMPEG_VFSCALE_validator
    forms.FFMPEG_VFSCALE_validator(None, DummyField(''))
    forms.FFMPEG_VFSCALE_validator(None, DummyField('1920:1080'))
    forms.FFMPEG_VFSCALE_validator(None, DummyField('-1:1080'))
    with pytest.raises(ValidationError, match='Invalid scale option'):
        forms.FFMPEG_VFSCALE_validator(None, DummyField('bad scale'))

    # FFMPEG_EXTRA_OPTIONS_validator
    forms.FFMPEG_EXTRA_OPTIONS_validator(None, DummyField(''))
    forms.FFMPEG_EXTRA_OPTIONS_validator(None, DummyField('-pix_fmt yuv420p'))
    with pytest.raises(ValidationError, match='Invalid characters'):
        forms.FFMPEG_EXTRA_OPTIONS_validator(None, DummyField('-bad?options!'))
    with pytest.raises(ValidationError, match='Options cannot begin with a space'):
        forms.FFMPEG_EXTRA_OPTIONS_validator(None, DummyField(' -pix_fmt yuv420p'))
    with pytest.raises(ValidationError, match='Options cannot end with a space'):
        forms.FFMPEG_EXTRA_OPTIONS_validator(None, DummyField('-pix_fmt yuv420p '))
    with pytest.raises(ValidationError, match='multiple concurrent space'):
        forms.FFMPEG_EXTRA_OPTIONS_validator(None, DummyField('-pix_fmt  yuv420p'))

    # TEXT_PROPERTIES__FONT_FACE_validator
    forms.TEXT_PROPERTIES__FONT_FACE_validator(None, DummyField('FONT_HERSHEY_SIMPLEX'))
    with pytest.raises(ValidationError, match='Invalid selection'):
        forms.TEXT_PROPERTIES__FONT_FACE_validator(None, DummyField('INVALID_FONT'))

    # TEXT_PROPERTIES__FONT_HEIGHT_validator
    with pytest.raises(ValidationError, match='Font height must be greater than 1'):
        forms.TEXT_PROPERTIES__FONT_HEIGHT_validator(None, DummyField(0))
    forms.TEXT_PROPERTIES__FONT_HEIGHT_validator(None, DummyField(10))

    # TEXT_PROPERTIES__FONT_X_validator & Y
    with pytest.raises(ValidationError, match='Font offset must be greater than 1'):
        forms.TEXT_PROPERTIES__FONT_X_validator(None, DummyField(0))
    forms.TEXT_PROPERTIES__FONT_X_validator(None, DummyField(10))

    with pytest.raises(ValidationError, match='Font offset must be greater than 1'):
        forms.TEXT_PROPERTIES__FONT_Y_validator(None, DummyField(0))
    forms.TEXT_PROPERTIES__FONT_Y_validator(None, DummyField(10))

    # TEXT_PROPERTIES__PIL_FONT_SIZE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.TEXT_PROPERTIES__PIL_FONT_SIZE_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Size must be 10 or greater'):
        forms.TEXT_PROPERTIES__PIL_FONT_SIZE_validator(None, DummyField(5))
    forms.TEXT_PROPERTIES__PIL_FONT_SIZE_validator(None, DummyField(20))


def test_moon_and_lightgraph_overlay_validators():
    # MOON_OVERLAY__X_validator & Y
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.MOON_OVERLAY__X_validator(None, DummyField(10.5))
    forms.MOON_OVERLAY__X_validator(None, DummyField(10))

    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.MOON_OVERLAY__Y_validator(None, DummyField(10.5))
    forms.MOON_OVERLAY__Y_validator(None, DummyField(10))

    # MOON_OVERLAY__SCALE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.MOON_OVERLAY__SCALE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Image scale must be 0.1 or more'):
        forms.MOON_OVERLAY__SCALE_validator(None, DummyField(0.05))
    with pytest.raises(ValidationError, match='Image scale must be 2.0 or less'):
        forms.MOON_OVERLAY__SCALE_validator(None, DummyField(2.5))
    forms.MOON_OVERLAY__SCALE_validator(None, DummyField(1.0))

    # MOON_OVERLAY__DARK_SIDE_SCALE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.MOON_OVERLAY__DARK_SIDE_SCALE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Dark side scale must be 0.0 or more'):
        forms.MOON_OVERLAY__DARK_SIDE_SCALE_validator(None, DummyField(-0.1))
    with pytest.raises(ValidationError, match='Dark side scale must 0.9 or less'):
        forms.MOON_OVERLAY__DARK_SIDE_SCALE_validator(None, DummyField(1.0))
    forms.MOON_OVERLAY__DARK_SIDE_SCALE_validator(None, DummyField(0.5))

    # LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Height must be 10 or more'):
        forms.LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator(None, DummyField(5))
    with pytest.raises(ValidationError, match='Height must 100 or less'):
        forms.LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator(None, DummyField(105))
    forms.LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator(None, DummyField(50))

    # LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Border must be 0 or more'):
        forms.LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Border must 10 or less'):
        forms.LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator(None, DummyField(11))
    forms.LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator(None, DummyField(2))

    # LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Must be 3 or more'):
        forms.LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator(None, DummyField(2))
    with pytest.raises(ValidationError, match='Must 20 or less'):
        forms.LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator(None, DummyField(21))
    forms.LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator(None, DummyField(5))

    # LIGHTGRAPH_OVERLAY__OPACITY_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LIGHTGRAPH_OVERLAY__OPACITY_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Opacity must be 0 or more'):
        forms.LIGHTGRAPH_OVERLAY__OPACITY_validator(None, DummyField(-1))
    with pytest.raises(ValidationError, match='Opacity must be 100 or less'):
        forms.LIGHTGRAPH_OVERLAY__OPACITY_validator(None, DummyField(101))
    forms.LIGHTGRAPH_OVERLAY__OPACITY_validator(None, DummyField(50))

    # LIGHTGRAPH_OVERLAY__OFFSET_X_validator & Y
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LIGHTGRAPH_OVERLAY__OFFSET_X_validator(None, DummyField(10.5))
    forms.LIGHTGRAPH_OVERLAY__OFFSET_X_validator(None, DummyField(10))

    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LIGHTGRAPH_OVERLAY__Y_validator(None, DummyField(10.5))
    forms.LIGHTGRAPH_OVERLAY__Y_validator(None, DummyField(10))

    # LIGHTGRAPH_OVERLAY__SCALE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.LIGHTGRAPH_OVERLAY__SCALE_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Must be greater than 0'):
        forms.LIGHTGRAPH_OVERLAY__SCALE_validator(None, DummyField(0.0))
    with pytest.raises(ValidationError, match='Must be 1.0 or less'):
        forms.LIGHTGRAPH_OVERLAY__SCALE_validator(None, DummyField(1.5))
    forms.LIGHTGRAPH_OVERLAY__SCALE_validator(None, DummyField(0.5))


def test_image_overlay_and_cardinal_dirs():
    # IMAGE_OVERLAY__LOAD_INTERVAL_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_OVERLAY__LOAD_INTERVAL_validator(None, DummyField(60.5))
    with pytest.raises(ValidationError, match='Must be 60 or more'):
        forms.IMAGE_OVERLAY__LOAD_INTERVAL_validator(None, DummyField(30))
    forms.IMAGE_OVERLAY__LOAD_INTERVAL_validator(None, DummyField(120))

    # IMAGE_OVERLAY__W_H_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_OVERLAY__W_H_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Must be 10 or more'):
        forms.IMAGE_OVERLAY__W_H_validator(None, DummyField(5))
    forms.IMAGE_OVERLAY__W_H_validator(None, DummyField(100))

    # IMAGE_OVERLAY__X_Y_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_OVERLAY__X_Y_validator(None, DummyField(10.5))
    forms.IMAGE_OVERLAY__X_Y_validator(None, DummyField(50))

    # CARDINAL_DIRS__CHAR_validator
    forms.CARDINAL_DIRS__CHAR_validator(None, DummyField(''))
    forms.CARDINAL_DIRS__CHAR_validator(None, DummyField('N'))
    with pytest.raises(ValidationError, match='String must be one character'):
        forms.CARDINAL_DIRS__CHAR_validator(None, DummyField('North'))

    # CARDINAL_DIRS__DIAMETER_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CARDINAL_DIRS__DIAMETER_validator(None, DummyField(100.5))
    with pytest.raises(ValidationError, match='Diameter must be 100 or greater'):
        forms.CARDINAL_DIRS__DIAMETER_validator(None, DummyField(50))
    forms.CARDINAL_DIRS__DIAMETER_validator(None, DummyField(500))

    # CARDINAL_DIRS__CENTER_OFFSET_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CARDINAL_DIRS__CENTER_OFFSET_validator(None, DummyField(10.5))
    forms.CARDINAL_DIRS__CENTER_OFFSET_validator(None, DummyField(10))

    # CARDINAL_DIRS__SIDE_OFFSET_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.CARDINAL_DIRS__SIDE_OFFSET_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Offset must be greater than -20'):
        forms.CARDINAL_DIRS__SIDE_OFFSET_validator(None, DummyField(-25))
    with pytest.raises(ValidationError, match='Offset must be less than 300'):
        forms.CARDINAL_DIRS__SIDE_OFFSET_validator(None, DummyField(305))
    forms.CARDINAL_DIRS__SIDE_OFFSET_validator(None, DummyField(50))


def test_font_and_orb_properties():
    # TEXT_PROPERTIES__FONT_SCALE_validator
    with pytest.raises(ValidationError, match='Font scale must be greater than 0.1'):
        forms.TEXT_PROPERTIES__FONT_SCALE_validator(None, DummyField(0.05))
    with pytest.raises(ValidationError, match='Font scale too large'):
        forms.TEXT_PROPERTIES__FONT_SCALE_validator(None, DummyField(105))
    forms.TEXT_PROPERTIES__FONT_SCALE_validator(None, DummyField(1.0))

    # TEXT_PROPERTIES__FONT_THICKNESS_validator
    with pytest.raises(ValidationError, match='Font thickness must be 1 or more'):
        forms.TEXT_PROPERTIES__FONT_THICKNESS_validator(None, DummyField(0))
    with pytest.raises(ValidationError, match='Font thickness must be less than 20'):
        forms.TEXT_PROPERTIES__FONT_THICKNESS_validator(None, DummyField(21))
    forms.TEXT_PROPERTIES__FONT_THICKNESS_validator(None, DummyField(2))

    # ORB_PROPERTIES__MODE_validator
    forms.ORB_PROPERTIES__MODE_validator(None, DummyField('ha'))
    forms.ORB_PROPERTIES__MODE_validator(None, DummyField('az'))
    forms.ORB_PROPERTIES__MODE_validator(None, DummyField('alt'))
    forms.ORB_PROPERTIES__MODE_validator(None, DummyField('off'))
    with pytest.raises(ValidationError, match='Please select a valid orb mode'):
        forms.ORB_PROPERTIES__MODE_validator(None, DummyField('invalid'))

    # ORB_PROPERTIES__RADIUS_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.ORB_PROPERTIES__RADIUS_validator(None, DummyField(10.5))
    with pytest.raises(ValidationError, match='Orb radius must be 1 or more'):
        forms.ORB_PROPERTIES__RADIUS_validator(None, DummyField(0))
    forms.ORB_PROPERTIES__RADIUS_validator(None, DummyField(10))

    # ORB_PROPERTIES__AZ_OFFSET_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.ORB_PROPERTIES__AZ_OFFSET_validator(None, DummyField('abc'))
    with pytest.raises(ValidationError, match='Azimuth Offset must be greater than -180'):
        forms.ORB_PROPERTIES__AZ_OFFSET_validator(None, DummyField(-185.0))
    with pytest.raises(ValidationError, match='Azimuth Offset must be less than 180'):
        forms.ORB_PROPERTIES__AZ_OFFSET_validator(None, DummyField(185.0))
    forms.ORB_PROPERTIES__AZ_OFFSET_validator(None, DummyField(45.0))

    # IMAGE_BORDER_SIDE_validator
    with pytest.raises(ValidationError, match='Please enter valid number'):
        forms.IMAGE_BORDER_SIDE_validator(None, DummyField(10.5))
    forms.IMAGE_BORDER_SIDE_validator(None, DummyField(10))
