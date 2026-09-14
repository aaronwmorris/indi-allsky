"""Unit tests for indi_allsky.flask.forms field validators.

Each entry in VALIDATOR_TEST_CASES is a 3-tuple:
    (validator_callable, valid_inputs_list, invalid_inputs_list)

To add tests for a new validator:
1. Append `(forms.<NAME>_validator, [valid_values], [invalid_values])` below.
2. Ensure invalid values cover type errors, upper/lower bounds, and regex mismatches.
"""

import os
import stat
import tempfile

import pytest
from wtforms.validators import ValidationError
from indi_allsky.flask import forms


class DummyField:
    def __init__(self, data):
        self.data = data


# ---------------------------------------------------------------------------
# DummyForm helpers for validators that reference form.<CHOICES>
# ---------------------------------------------------------------------------
class DummyForm:
    """Minimal form stub whose attributes are set dynamically per-test."""
    pass


def _make_form(**attrs):
    """Return a DummyForm with arbitrary attributes."""
    f = DummyForm()
    for k, v in attrs.items():
        setattr(f, k, v)
    return f


# ====================================================================
# Main table-driven test cases
# ====================================================================
VALIDATOR_TEST_CASES = [
    # --- Group 1: URI & Network ---
    (
        forms.SQLALCHEMY_DATABASE_URI_validator,
        ["sqlite:////var/lib/indi-allsky/indi-allsky.sqlite", "postgresql://user:pass@localhost:5432/db"],
        ["bad uri with spaces", "sqlite:///invalid$$$chars"],
    ),
    (
        forms.INDI_SERVER_validator,
        ["localhost", "192.168.1.100", "indi_host-01", ""],
        ["invalid host space", "host#name"],
    ),
    (
        forms.INDI_PORT_validator,
        [7624, 0, 65535, 80],
        [-1, 65536, "not_an_int", 70000],
    ),
    (
        forms.OWNER_validator,
        ["Observatory Admin", "John Doe-Smith_01", ""],
        ["Invalid<Name>", "Name with $ymbols!"],
    ),
    # No-op validators
    (
        forms.INDI_CAMERA_NAME_validator,
        ["", "CCD Simulator", "ZWO ASI120MC"],
        [],
    ),
    (
        forms.WEBSITE__TITLE_validator,
        ["", "Allsky Camera", "My Observatory", 123],
        [],
    ),
    (
        forms.LENS_NAME_validator,
        ["", "Arecont 1.55mm", "Fish-eye Lens"],
        [],
    ),

    # --- Group 2: Optics & Geometry ---
    (
        forms.LENS_FOCAL_LENGTH_validator,
        [2.1, 50, 1.4, 100.0],
        [0.0, -1.0, -5, "string"],
    ),
    (
        forms.LENS_FOCAL_RATIO_validator,
        [1.4, 2.8, 0.95, 11],
        [0.0, -0.5, -2, "string"],
    ),
    (
        forms.LENS_IMAGE_CIRCLE_validator,
        [1800, 1000, 500],
        [0, -100, "string", 1.5],
    ),
    (
        forms.LENS_OFFSET_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    (
        forms.LENS_ALTITUDE_validator,
        [0.0, 45.0, 90.0, 0, 90],
        [-0.1, -10.0, 90.1, 100.0, "string"],
    ),
    (
        forms.LENS_AZIMUTH_validator,
        [0.0, 180.0, 360.0, 0, 360],
        [-0.1, -5.0, 360.1, 400.0, "string"],
    ),

    # --- Group 3: Exposure & Camera Sensors ---
    (
        forms.CCD_GAIN_validator,
        [0, 100, 300, 0.0, 150.5],
        [-1, -0.1, -50, "string"],
    ),
    (
        forms.CCD_BINNING_validator,
        [1, 2, 3, 4],
        [0, -1, 5, 6, "string", 1.5],
    ),
    (
        forms.CCD_EXPOSURE_validator,
        [0.0, 30.0, 120.0, 0, 60],
        [-0.1, -1.0, 120.1, 150.0, "string"],
    ),
    (
        forms.CAMERA_SQM__EXPOSURE_validator,
        [1.0, 30.0, 60.0, 1, 60],
        [0.9, 0.0, -1.0, 60.1, 70.0, "string"],
    ),
    (
        forms.CCD_EXPOSURE_TIMEOUT_validator,
        [120, 180, 300],
        [119, 0, -1, "string", 120.5],
    ),
    (
        forms.EXPOSURE_PERIOD_validator,
        [1.0, 5.0, 60.0, 1],
        [0.9, 0.0, -1.0, "string"],
    ),
    (
        forms.EXPOSURE_PERIOD_DAY_validator,
        [1.0, 10.0, 120.0, 1],
        [0.9, 0.0, -1.0, "string"],
    ),
    # CAMERA_SQM__EXPOSURE_PERIOD: int only, >= 60
    (
        forms.CAMERA_SQM__EXPOSURE_PERIOD_validator,
        [60, 120, 300],
        [59, 0, -1, 60.5, "string"],
    ),
    # SQM_MAGNITUDE_OFFSET: (int, float), >= 0
    (
        forms.SQM_MAGNITUDE_OFFSET_validator,
        [0, 0.0, 15.5, 22.0],
        [-0.1, -1, -5.0, "string"],
    ),

    # --- Group 4: Timelapse & Keogram Settings ---
    (
        forms.TIMELAPSE_SKIP_FRAMES_validator,
        [0, 1, 5, 10],
        [-1, -10, "string", 1.5],
    ),
    (
        forms.TIMELAPSE__KEOGRAM_RATIO_validator,
        [0.01, 0.15, 0.33],
        [0.009, 0.0, -0.1, 0.331, 0.5, "string", 1],
    ),
    (
        forms.TIMELAPSE__PRE_SCALE_validator,
        [1, 50, 100],
        [0, -1, 101, 200],
    ),
    # TIMELAPSE__IMAGE_CIRCLE: int only, >= 100
    (
        forms.TIMELAPSE__IMAGE_CIRCLE_validator,
        [100, 1000, 4000],
        [99, 0, -1, 100.5, "string"],
    ),

    # --- Group 5: Image Processing & Denoise ---
    (
        forms.CCD_BIT_DEPTH_validator,
        [0, 8, 10, 12, 14, 16, "0", "8", "16"],
        [1, 4, 24, 32, 64],
    ),
    (
        forms.CCD_TEMP_validator,
        [-50, -49.9, 0.0, 25.0, 50],
        [-51, -50.1, -100, "string"],
    ),
    (
        forms.FOCUS_DELAY_validator,
        [1.0, 5.0, 10],
        [0.9, 0.0, -1.0, "string"],
    ),
    (
        forms.WB_FACTOR_validator,
        [0.0, 1.5, 4.0, 0, 4],
        [-0.1, -1.0, 4.01, 5.0, "string"],
    ),
    (
        forms.WB_MTF_MIDTONES_validator,
        [0.0, 0.5, 1.0, 0, 1],
        [-0.1, -1.0, 1.01, 2.0, "string"],
    ),
    (
        forms.SATURATION_FACTOR_validator,
        [0.0, 1.2, 4.0, 0, 4],
        [-0.1, -1.0, 4.01, 5.0, "string"],
    ),
    (
        forms.GAMMA_CORRECTION_validator,
        [0.1, 1.8, 2.2, 1],
        [0.0, -0.1, -1.0, "string"],
    ),
    (
        forms.SHARPEN_AMOUNT_validator,
        [0.0, 1.0, 2.0, 0, 2],
        [-0.1, -1.0, 2.01, 3.0, "string"],
    ),
    (
        forms.SCNR_MTF_MIDTONES_validator,
        [0.5, 0.75, 1.0],
        [0.49, 0.0, -0.5, 1.01, 2.0, "string"],
    ),
    (
        forms.IMAGE_DENOISE_STRENGTH_validator,
        [1, 3, 5, 1.0, 5.0],
        [0, 0.9, 6, 5.1, "string"],
    ),
    (
        forms.BILATERAL_SIGMA_validator,
        [1, 25, 50, 1.0, 50.0],
        [0, 0.9, 51, 50.1, "string"],
    ),

    # --- Group 6: Location & Astrometric Coordinates ---
    (
        forms.LOCATION_LATITUDE_validator,
        [-90.0, -34.9285, 0.0, 45.0, 90.0],
        [-90.1, -100.0, 90.1, 100.0, "string"],
    ),
    (
        forms.LOCATION_LONGITUDE_validator,
        [-180.0, -120.0, 0.0, 138.6007, 180.0],
        [-180.1, -200.0, 180.1, 200.0, "string"],
    ),
    (
        forms.LOCATION_ELEVATION_validator,
        [-500, 0, 150, 8848],
        ["string", 150.5],
    ),
    (
        forms.LOCATION_NAME_validator,
        ["", "Home Observatory"],
        [],
    ),
    (
        forms.NIGHT_SUN_ALT_DEG_validator,
        [-90.0, -6.0, 0.0, 90.0],
        [-90.1, 90.1, "string"],
    ),
    (
        forms.NIGHT_MOONMODE_ALT_DEG_validator,
        [-90.0, 0.0, 45.0, 91.0],
        [-90.1, 91.1, "string"],
    ),
    (
        forms.NIGHT_MOONMODE_PHASE_validator,
        [0.0, 50.0, 100.0, 0, 100],
        [-0.1, -1.0, 100.1, 150.0, "string"],
    ),

    # --- Group 7: Stretching Modes ---
    (
        forms.IMAGE_STRETCH__MODE1_GAMMA_validator,
        [0.0, 0.1, 2.2, 5.0, 1],
        [-0.1, -1.0, "string"],
    ),
    (
        forms.IMAGE_STRETCH__MODE1_STDDEVS_validator,
        [1.0, 3.0, 10.0, 1],
        [0.9, 0.0, -0.1, -1.0, "string"],
    ),
    (
        forms.IMAGE_STRETCH__MODE2_SHADOWS_validator,
        [0.0, 0.05, 0.5],
        [-0.01, -1.0, 0.51, 1.0, "string"],
    ),
    (
        forms.IMAGE_STRETCH__MODE2_MIDTONES_validator,
        [0.0, 0.5, 1.0],
        [-0.01, -1.0, 1.01, 2.0, "string"],
    ),
    (
        forms.IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator,
        [0.5, 0.95, 1.0],
        [0.49, 0.0, -0.1, 1.01, 2.0, "string"],
    ),
    (
        forms.IMAGE_STRETCH__MODE3_BLACK_CLIP_validator,
        [-10.0, -5.0, 0.0],
        [-10.1, -20.0, 0.01, 1.0, "string"],
    ),
    (
        forms.IMAGE_STRETCH__MODE3_SHADOWS_validator,
        [0.0, 0.05, 0.5],
        [-0.01, -1.0, 0.51, 1.0, "string"],
    ),
    (
        forms.IMAGE_STRETCH__MODE3_MIDTONES_validator,
        [0.0, 0.5, 1.0],
        [-0.01, -1.0, 1.01, 2.0, "string"],
    ),
    (
        forms.IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator,
        [0.5, 0.95, 1.0],
        [0.49, 0.0, -0.1, 1.01, 2.0, "string"],
    ),

    # --- Group 8: Keograms & Star Trails ---
    (
        forms.KEOGRAM_ANGLE_validator,
        [-180.0, 0.0, 90.0, 180.0],
        [-180.1, 180.1, "string"],
    ),
    (
        forms.STARTRAILS_MAX_ADU_validator,
        [1, 100, 255],
        [0, -1, 256, 1000],
    ),
    (
        forms.STARTRAILS_MASK_THOLD_validator,
        [1, 100, 255],
        [0, -1, 256, 1000],
    ),
    (
        forms.STARTRAILS_PIXEL_THOLD_validator,
        [0, 1, 50, 100, 0.0, 100.0],
        [-1, -0.1, 101, 100.1, "string"],
    ),

    # --- Group 9: Calibration & Image Repair ---
    # IMAGE_CALIBRATE_HOLE_THOLD: int, >0 and <=100 (< is used for upper: >100)
    (
        forms.IMAGE_CALIBRATE_HOLE_THOLD_validator,
        [1, 50, 100],
        [0, -1, 101, 200, 50.5, "string"],
    ),
    # IMAGE_CALIBRATE_MANUAL_OFFSET: int, >= 0
    (
        forms.IMAGE_CALIBRATE_MANUAL_OFFSET_validator,
        [0, 50, 100],
        [-1, -50, "string", 1.5],
    ),
    # ASI676MC REPAIR validators (boundary constants from asi676mc.py)
    # RATIO_THRESHOLD: >0 and <=100.0
    (
        forms.IMAGE_ASI676MC_REPAIR__RATIO_THRESHOLD_validator,
        [0.01, 1.5, 50.0, 100.0, 1],
        [0, 0.0, -0.1, 100.1, float('inf'), float('nan'), "string"],
    ),
    # SAMPLE_STEP: int, even, 2..256
    (
        forms.IMAGE_ASI676MC_REPAIR__SAMPLE_STEP_validator,
        [2, 16, 64, 256],
        [0, 1, 3, 257, -2, 2.0, "string"],
    ),
    # SOURCE_SATURATION_THRESHOLD: int, 1..65535
    (
        forms.IMAGE_ASI676MC_REPAIR__SOURCE_SATURATION_THRESHOLD_validator,
        [1, 1000, 32768, 65535],
        [0, -1, 65536, 1.0, "string"],
    ),
    # GAIN: (int, float) finite, 0.1..10.0
    (
        forms.IMAGE_ASI676MC_REPAIR__GAIN_validator,
        [0.1, 1.0, 5.0, 10.0, 1],
        [0.09, 0.0, -0.1, 10.01, float('inf'), float('nan'), "string"],
    ),
    # HIGHLIGHT_BLEND_RATIO: >0 and <=1
    (
        forms.IMAGE_ASI676MC_REPAIR__HIGHLIGHT_BLEND_RATIO_validator,
        [0.01, 0.5, 1.0, 1],
        [0, 0.0, -0.1, 1.01, float('inf'), float('nan'), "string"],
    ),
    # CHUNK_ROWS: int, even, 2..4096
    (
        forms.IMAGE_ASI676MC_REPAIR__CHUNK_ROWS_validator,
        [2, 128, 1024, 4096],
        [0, 1, 3, 4097, -2, 128.0, "string"],
    ),

    # --- Group 10: Star & Meteor Detection ---
    # DETECT_STARS_THOLD: >0 and <=1.0 (uses <= for 0 check)
    (
        forms.DETECT_STARS_THOLD_validator,
        [0.001, 0.5, 1.0, 1],
        [0.0, 0, -0.1, 1.01, 2.0, "string"],
    ),
    (
        forms.DETECT_STARS_SEP_THOLD_validator,
        [0.5, 25.0, 50.0, 1],
        [0.49, 0.0, -1.0, 50.1, 100.0, "string"],
    ),
    (
        forms.DETECT_STARS_SEP_MAX_RADIUS_validator,
        [1, 250, 500],
        [0, -1, 501, 1000, "string", 1.5],
    ),
    # DETECT_METEORS_THOLD: int, >10 and <=1000
    (
        forms.DETECT_METEORS_THOLD_validator,
        [11, 500, 1000],
        [10, 0, -1, 1001, "string", 15.5],
    ),

    # --- Group 11: CLAHE ---
    # CLAHE_CLIPLIMIT: >0 (strict) and <60 (uses >60, so 60 valid)
    (
        forms.CLAHE_CLIPLIMIT_validator,
        [0.1, 2.0, 30.0, 60, 60.0],
        [0, 0.0, -1, 60.1, 70, "string"],
    ),
    # CLAHE_GRIDSIZE: int, >=4 and <=64
    (
        forms.CLAHE_GRIDSIZE_validator,
        [4, 8, 32, 64],
        [3, 0, -1, 65, 100, "string", 8.5],
    ),

    # --- Group 12: Image Labeling ---
    (
        forms.IMAGE_LABEL_SYSTEM_validator,
        ["", "opencv", "pillow"],
        ["invalid_system", "cairo", "PIL"],
    ),
    # IMAGE_LABEL_TEMPLATE: format string with known keys
    (
        forms.IMAGE_LABEL_TEMPLATE_validator,
        ["", "{exposure}s @ gain {gain}", "{location} - {timestamp:%Y-%m-%d}", "Plain text", "{stars} stars, SQM: {sqm}"],
        ["{unknown_key}", "{invalid_placeholder}"],
    ),
    # WEB_STATUS_TEMPLATE: format string with known keys
    (
        forms.WEB_STATUS_TEMPLATE_validator,
        ["", "{status} {exposure}s", "{camera_name} - {temp}C", "Status: {mode}", "{kpindex:.1f}"],
        ["{unknown_key}", "{invalid_placeholder}"],
    ),
    # WEBSOCKET_API_KEY: regex ^[a-zA-Z0-9_\-]+$ or empty
    (
        forms.WEBSOCKET_API_KEY_validator,
        ["", "my-secret-key_123", "APIKEY123", "a_b-c"],
        ["bad key with spaces", "secret@key!", "api#key$"],
    ),
    # IMAGE_STRETCH__CLASSNAME: regex ^[a-zA-Z0-9_\-]+$ or empty
    (
        forms.IMAGE_STRETCH__CLASSNAME_validator,
        ["", "stretch_mode_1", "StretchClass-01", "custom_stretch"],
        ["invalid class", "stretch@mode!"],
    ),

    # --- Group 13: Image Transformation & Rotation ---
    # IMAGE_ROTATE: specific string values or empty
    (
        forms.IMAGE_ROTATE_validator,
        ["", "ROTATE_90_CLOCKWISE", "ROTATE_90_COUNTERCLOCKWISE", "ROTATE_180"],
        ["ROTATE_270", "INVALID_ROTATE"],
    ),
    # IMAGE_ROTATE_ANGLE: int, -180..180
    (
        forms.IMAGE_ROTATE_ANGLE_validator,
        [-180, 0, 90, 180],
        [-181, 181, -200, 200, "string", 45.5],
    ),

    # --- Group 14: Keogram Scaling & Cropping ---
    # KEOGRAM_H_SCALE: >0 (strict) and <=100
    (
        forms.KEOGRAM_H_SCALE_validator,
        [0.1, 1, 50, 100],
        [0, 0.0, -1, 101, 150],
    ),
    (
        forms.KEOGRAM_V_SCALE_validator,
        [0.1, 1, 50, 100],
        [0, 0.0, -1, 101, 150],
    ),
    # KEOGRAM_CROP_TOP: >=0 and <=49
    (
        forms.KEOGRAM_CROP_TOP_validator,
        [0, 25, 49],
        [-1, 50, 100],
    ),
    (
        forms.KEOGRAM_CROP_BOTTOM_validator,
        [0, 25, 49],
        [-1, 50, 100],
    ),
    # LONGTERM_KEOGRAM offsets: int only
    (
        forms.LONGTERM_KEOGRAM__OFFSET_X_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    (
        forms.LONGTERM_KEOGRAM__OFFSET_Y_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    # LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE: format string with {month}
    (
        forms.LONGTERM_KEOGRAM__MONTH_LABEL_TEMPLATE_validator,
        ["", "{month:%B %Y}", "{month}", "Static Label"],
        ["{bad_key}", "{unknown}"],
    ),
    # REALTIME_KEOGRAM__MAX_ENTRIES: int, 0..10000
    (
        forms.REALTIME_KEOGRAM__MAX_ENTRIES_validator,
        [0, 1000, 5000, 10000],
        [-1, -10, 10001, "string", 500.5],
    ),
    # REALTIME_KEOGRAM__SAVE_INTERVAL: int, 1..100
    (
        forms.REALTIME_KEOGRAM__SAVE_INTERVAL_validator,
        [1, 10, 50, 100],
        [0, -1, 101, "string", 5.5],
    ),

    # --- Group 15: Star Trails Extended ---
    # STARTRAILS_MIN_STARS: int, >= 0 (uses < 0)
    (
        forms.STARTRAILS_MIN_STARS_validator,
        [0, 5, 50, 100],
        [-1, -10, "string", 5.5],
    ),
    # STARTRAILS_TIMELAPSE_MINFRAMES: int, >= 25
    (
        forms.STARTRAILS_TIMELAPSE_MINFRAMES_validator,
        [25, 50, 1000],
        [24, 0, -1, "string", 25.5],
    ),
    # SUN_ALT_THOLD: (int, float), -90..90 (uses < -90 and > 90)
    (
        forms.STARTRAILS_SUN_ALT_THOLD_validator,
        [-90.0, -90, -6.0, 0.0, 90.0, 90],
        [-90.1, -100, 90.1, 100, "string"],
    ),
    # MOON_ALT_THOLD: -90..91 (uses > 91)
    (
        forms.STARTRAILS_MOON_ALT_THOLD_validator,
        [-90.0, -90, 0.0, 90.0, 91.0, 91],
        [-90.1, -100, 91.1, 100, "string"],
    ),
    # MOON_PHASE_THOLD: 0..101 (uses > 101)
    (
        forms.STARTRAILS_MOON_PHASE_THOLD_validator,
        [0.0, 0, 50.0, 100.0, 101.0, 101],
        [-0.1, -1.0, 101.1, 150, "string"],
    ),

    # --- Group 16: Queue Management ---
    (
        forms.IMAGE_QUEUE_MAX_validator,
        [2, 5, 100],
        [1, 0, -1, "string", 2.5],
    ),
    (
        forms.IMAGE_QUEUE_MIN_validator,
        [1, 5, 50],
        [0, -1, -5, "string", 1.5],
    ),
    # IMAGE_QUEUE_BACKOFF: >0 (strict)
    (
        forms.IMAGE_QUEUE_BACKOFF_validator,
        [0.1, 1.0, 2.5, 5, 10],
        [0, 0.0, -0.1, -1.0, "string"],
    ),

    # --- Group 17: Compression ---
    (
        forms.IMAGE_FILE_COMPRESSION__JPG_validator,
        [1, 50, 95, 100],
        [0, -1, 101, 150],
    ),
    (
        forms.IMAGE_FILE_COMPRESSION__PNG_validator,
        [1, 5, 9],
        [0, -1, 10, 20],
    ),

    # --- Group 18: Image Scale ---
    # IMAGE_SCALE: >= 1 and <= 100
    (
        forms.IMAGE_SCALE_validator,
        [1, 50, 100],
        [0, -1, 101, 150],
    ),

    # --- Group 19: Image Export ---
    # IMAGE_EXPORT_RAW: specific strings or empty
    (
        forms.IMAGE_EXPORT_RAW_validator,
        ["", "png", "tif", "jpg", "jp2", "webp"],
        ["gif", "bmp", "fits"],
    ),

    # --- Group 20: ADU & ROI ---
    # TARGET_ADU: >0 (strict) and <255 (uses >255)
    (
        forms.TARGET_ADU_validator,
        [1, 128, 255],
        [0, 0.0, -1, 256, 300],
    ),
    (
        forms.TARGET_ADU_DAY_validator,
        [1, 128, 255],
        [0, 0.0, -1, 256, 300],
    ),
    # TARGET_ADU_DEV: >0 (strict) and <100 (uses >100)
    (
        forms.TARGET_ADU_DEV_validator,
        [1, 50, 100],
        [0, 0.0, -1, 101, 150],
    ),
    (
        forms.TARGET_ADU_DEV_DAY_validator,
        [1, 50, 100],
        [0, 0.0, -1, 101, 150],
    ),
    # ADU_ROI: int, >= 0
    (
        forms.ADU_ROI_validator,
        [0, 100, 500],
        [-1, -50, 10.5, "string"],
    ),
    (
        forms.SQM_ROI_validator,
        [0, 100, 500],
        [-1, -50, 10.5, "string"],
    ),
    # ADU_FOV_DIV: int(field.data) in (2, 3, 4, 6)
    (
        forms.ADU_FOV_DIV_validator,
        [2, 3, 4, 6, "2", "6"],
        [1, 5, 7, 0, -1],
    ),
    # SQM_FOV_DIV: same pattern
    (
        forms.SQM_FOV_DIV_validator,
        [2, 3, 4, 6, "2", "6"],
        [1, 5, 7, 0, -1],
    ),

    # --- Group 21: Scripts & Execution ---
    # HOOK_TIMEOUT: int, >= 0 and <20 (uses >20, so 20 valid)
    (
        forms.HOOK_TIMEOUT_validator,
        [0, 10, 20],
        [-1, -10, 21, 50, 5.0, "string"],
    ),

    # --- Group 22: Circular Mask ---
    (
        forms.IMAGE_CIRCLE_MASK__DIAMETER_validator,
        [100, 500, 2000],
        [99, 0, -1, "string", 100.5],
    ),
    (
        forms.IMAGE_CIRCLE_MASK__OFFSET_X_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    (
        forms.IMAGE_CIRCLE_MASK__OFFSET_Y_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    # IMAGE_CIRCLE_MASK__BLUR: int, >= 0, if > 0 must be odd
    (
        forms.IMAGE_CIRCLE_MASK__BLUR_validator,
        [0, 1, 3, 99],
        [-1, -2, 2, 4, "string", 1.5],
    ),
    # IMAGE_CIRCLE_MASK__OPACITY: int, 0..100
    (
        forms.IMAGE_CIRCLE_MASK__OPACITY_validator,
        [0, 50, 100],
        [-1, 101, "string", 50.5],
    ),

    # --- Group 23: Fish2Pano ---
    (
        forms.FISH2PANO__DIAMETER_validator,
        [100, 1000, 2000],
        [99, 0, -1, "string", 100.5],
    ),
    (
        forms.FISH2PANO__OFFSET_X_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    (
        forms.FISH2PANO__OFFSET_Y_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    # FISH2PANO__ROTATE_ANGLE: (int, float), -180..180
    (
        forms.FISH2PANO__ROTATE_ANGLE_validator,
        [-180.0, -180, 0.0, 0, 180, 180.0],
        [-180.1, -190, 180.1, 200, "string"],
    ),
    # FISH2PANO__SCALE: (int, float), 0.1..1.0
    (
        forms.FISH2PANO__SCALE_validator,
        [0.1, 0.5, 1.0, 1],
        [0.09, 0.0, -0.1, 1.01, 2.0, "string"],
    ),
    # FISH2PANO__MODULUS: int, >= 1
    (
        forms.FISH2PANO__MODULUS_validator,
        [1, 2, 10],
        [0, -1, "string", 1.5],
    ),

    # --- Group 24: Image Cropping & Stacking ---
    (
        forms.IMAGE_CROP_ROI_validator,
        [0, 100, 500],
        [-1, -10, "string", 1.5],
    ),
    # IMAGE_STACK_METHOD: specific strings
    (
        forms.IMAGE_STACK_METHOD_validator,
        ["maximum", "average", "minimum"],
        ["invalid", "sum", "", 123],
    ),
    # IMAGE_STACK_COUNT: int(field.data) >= 1
    (
        forms.IMAGE_STACK_COUNT_validator,
        [1, 5, 100, "1", "10"],
        [0, -1, "0", "-5", "abc"],
    ),

    # --- Group 25: Image Alignment ---
    # IMAGE_ALIGN_DETECTSIGMA: int, >=2 and <=20 (uses <2 and >20)
    (
        forms.IMAGE_ALIGN_DETECTSIGMA_validator,
        [2, 10, 20],
        [1, 0, -1, 21, 50, "string", 2.5],
    ),
    # IMAGE_ALIGN_POINTS: int, >=25 and <=200
    (
        forms.IMAGE_ALIGN_POINTS_validator,
        [25, 100, 200],
        [24, 0, -1, 201, 300, "string", 25.5],
    ),
    # IMAGE_ALIGN_SOURCEMINAREA: int, >=3 and <=25
    (
        forms.IMAGE_ALIGN_SOURCEMINAREA_validator,
        [3, 10, 25],
        [2, 0, -1, 26, 50, "string", 3.5],
    ),

    # --- Group 26: Expiration ---
    (
        forms.IMAGE_EXPIRE_DAYS_validator,
        [1, 30, 90],
        [0, -1, "string", 1.5],
    ),
    (
        forms.TIMELAPSE_EXPIRE_DAYS_validator,
        [1, 30, 90],
        [0, -1, "string", 1.5],
    ),

    # --- Group 27: FFMPEG ---
    # FFMPEG_FRAMERATE: no isinstance check; <10 and >60 (both strict)
    (
        forms.FFMPEG_FRAMERATE_validator,
        [10, 25, 30, 60],
        [9, 0, -1, 61, 100],
    ),
    # FFMPEG_BITRATE: regex ^\d+[km]$
    (
        forms.FFMPEG_BITRATE_validator,
        ["1000k", "5m", "2500k", "100m"],
        ["1000K", "5M", "1000", "k", "m", "abc", ""],
    ),
    # FFMPEG_VFSCALE: empty OK, else regex ^[a-z0-9\-\*\.]+\:[a-z0-9\-\*\.]+$
    (
        forms.FFMPEG_VFSCALE_validator,
        ["", "1920:1080", "iw*0.5:ih*0.5", "-1:720"],
        ["1920", "1920x1080"],
    ),
    # FFMPEG_EXTRA_OPTIONS: empty OK, else regex + no leading/trailing/double spaces
    (
        forms.FFMPEG_EXTRA_OPTIONS_validator,
        ["", "-preset fast", "-crf 23 -tune stillimage"],
        [" -preset fast", "-preset fast ", "-preset  fast", "-option $bad"],
    ),

    # --- Group 28: Text Properties & Fonts ---
    (
        forms.TEXT_PROPERTIES__FONT_FACE_validator,
        ["FONT_HERSHEY_SIMPLEX", "FONT_HERSHEY_PLAIN", "FONT_HERSHEY_COMPLEX"],
        ["FONT_ARIAL", "invalid_font", "", 123],
    ),
    # FONT_HEIGHT: <1 is invalid (no isinstance check)
    (
        forms.TEXT_PROPERTIES__FONT_HEIGHT_validator,
        [1, 10, 20],
        [0, -1, -10],
    ),
    (
        forms.TEXT_PROPERTIES__FONT_X_validator,
        [1, 10, 50],
        [0, -1, -10],
    ),
    (
        forms.TEXT_PROPERTIES__FONT_Y_validator,
        [1, 10, 50],
        [0, -1, -10],
    ),
    # PIL_FONT_SIZE: int, >= 10
    (
        forms.TEXT_PROPERTIES__PIL_FONT_SIZE_validator,
        [10, 12, 30],
        [9, 0, -1, "string", 10.5],
    ),
    # FONT_SCALE: >= 0.1 and <= 100 (uses <0.1 and >100)
    (
        forms.TEXT_PROPERTIES__FONT_SCALE_validator,
        [0.1, 1.0, 2, 100],
        [0.09, 0.0, -1.0, 101, 150],
    ),
    # FONT_THICKNESS: >= 1 and <20 (uses >20)
    (
        forms.TEXT_PROPERTIES__FONT_THICKNESS_validator,
        [1, 2, 5, 20],
        [0, -1, 21, 30],
    ),

    # --- Group 29: Moon & Lightgraph Overlays ---
    (
        forms.MOON_OVERLAY__X_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    (
        forms.MOON_OVERLAY__Y_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    # MOON_OVERLAY__SCALE: 0.1..2.0 (uses <0.1 and >2.0)
    (
        forms.MOON_OVERLAY__SCALE_validator,
        [0.1, 1.0, 1, 2.0, 2],
        [0.09, 0.0, -0.1, 2.01, 3.0, "string"],
    ),
    # DARK_SIDE_SCALE: 0.0..0.9 (uses <0.0 and >0.9)
    (
        forms.MOON_OVERLAY__DARK_SIDE_SCALE_validator,
        [0.0, 0, 0.5, 0.9],
        [-0.01, -1.0, 0.91, 1.0, "string"],
    ),
    # LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT: int, 10..100
    (
        forms.LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator,
        [10, 50, 100],
        [9, 0, -1, 101, 150, "string", 10.5],
    ),
    (
        forms.LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator,
        [0, 5, 10],
        [-1, -5, 11, 20, "string", 5.5],
    ),
    (
        forms.LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator,
        [3, 10, 20],
        [2, 0, -1, 21, 50, "string", 3.5],
    ),
    (
        forms.LIGHTGRAPH_OVERLAY__OPACITY_validator,
        [0, 50, 100],
        [-1, 101, "string", 50.5],
    ),
    (
        forms.LIGHTGRAPH_OVERLAY__OFFSET_X_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    (
        forms.LIGHTGRAPH_OVERLAY__Y_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    # LIGHTGRAPH_OVERLAY__SCALE: <=0.0 invalid (strict), <=1.0 ok
    (
        forms.LIGHTGRAPH_OVERLAY__SCALE_validator,
        [0.01, 0.5, 1.0, 1],
        [0.0, 0, -0.1, -1.0, 1.01, 2.0, "string"],
    ),
    # RGB_COLOR_validator (no 0,0,0 restriction — that's LIGHTGRAPH specific)
    (
        forms.LIGHTGRAPH_OVERLAY__RGB_COLOR_validator,
        ["255,255,255", "128,128,128", "1,0,0", "0,255,0"],
        ["0,0,0", "256,0,0", "0,0,300", "255,255", "bad,color,syntax", ""],
    ),

    # --- Group 30: Image Overlay & Cardinal Directions ---
    (
        forms.IMAGE_OVERLAY__URL_validator,
        ["", "http://example.com/overlay.png", "https://allsky.local/image.jpg", "file:///tmp/overlay.png"],
        ["not_a_url", "example.com/overlay.png"],
    ),
    (
        forms.IMAGE_OVERLAY__LOAD_INTERVAL_validator,
        [60, 120, 3600],
        [59, 0, -1, "string", 60.5],
    ),
    (
        forms.IMAGE_OVERLAY__W_H_validator,
        [10, 100, 1920],
        [9, 0, -1, "string", 10.5],
    ),
    (
        forms.IMAGE_OVERLAY__X_Y_validator,
        [-100, 0, 100],
        ["string", 1.5],
    ),
    # CARDINAL_DIRS__CHAR: empty OK, else exactly 1 character
    (
        forms.CARDINAL_DIRS__CHAR_validator,
        ["", "N", "S", "E", "W"],
        ["North", "NE", "  "],
    ),
    (
        forms.CARDINAL_DIRS__DIAMETER_validator,
        [100, 500, 2000],
        [99, 0, -1, "string", 100.5],
    ),
    (
        forms.CARDINAL_DIRS__CENTER_OFFSET_validator,
        [-50, 0, 50],
        ["string", 1.5],
    ),
    # CARDINAL_DIRS__SIDE_OFFSET: int, >-20 (strict) and <300 (strict)
    (
        forms.CARDINAL_DIRS__SIDE_OFFSET_validator,
        [-20, 0, 50, 300],
        [-21, -50, 301, 400, "string", 0.5],
    ),
    # RGB_COLOR: general (allows 0,0,0)
    (
        forms.RGB_COLOR_validator,
        ["0,0,0", "255,255,255", "128,64,32"],
        ["256,0,0", "0,0,300", "255,255", "invalid", ""],
    ),

    # --- Group 31: Orb Properties & Image Border ---
    (
        forms.ORB_PROPERTIES__MODE_validator,
        ["ha", "az", "alt", "off"],
        ["invalid", "on", "", 123],
    ),
    (
        forms.ORB_PROPERTIES__RADIUS_validator,
        [1, 5, 20],
        [0, -1, "string", 1.5],
    ),
    # AZ_OFFSET: >-180 (strict) and <180 (strict)
    (
        forms.ORB_PROPERTIES__AZ_OFFSET_validator,
        [-180, 0, 45.5, 180],
        [-180.1, -190, 180.1, 200, "string"],
    ),
    # IMAGE_BORDER_SIDE: int, >=0 and <1000 (uses >1000)
    (
        forms.IMAGE_BORDER_SIDE_validator,
        [0, 50, 500, 1000],
        [-1, -10, 1001, 2000, "string", 0.5],
    ),
    # UPLOAD_WORKERS: int, >=1 and <5 (uses >4)
    (
        forms.UPLOAD_WORKERS_validator,
        [1, 2, 3, 4],
        [0, -1, 5, 6, "string", 1.5],
    ),

    # --- Group 32: File Transfer ---
    (
        forms.FILETRANSFER__HOST_validator,
        ["", "localhost", "192.168.1.10", "remote.host.com", "[::1]:22", "host_name-1"],
        ["host with spaces", "host$name", "host#name"],
    ),
    (
        forms.FILETRANSFER__PORT_validator,
        [0, 21, 22, 65535],
        [-1, 65536, 70000, "string", 22.5],
    ),
    (
        forms.FILETRANSFER__USERNAME_validator,
        ["", "admin", "user@domain.com", "DOMAIN\\user", "first last"],
        ["user$name", "user#123", "user!name"],
    ),
    # Password validators are pass-through (no validation)
    (
        forms.FILETRANSFER__PASSWORD_validator,
        ["password123", "", "secret!@#", None, 123],
        [],
    ),
    # FILETRANSFER__TIMEOUT: <1 invalid, >1200 invalid
    (
        forms.FILETRANSFER__TIMEOUT_validator,
        [1, 600, 1200],
        [0, -1, 1201],
    ),
    # FILETRANSFER__REMOTE_NAME: regex + format template
    (
        forms.FILETRANSFER__REMOTE_NAME_validator,
        ["image.jpg", "allsky_{ts}_{timeofday}.{ext}", "allsky_{timestamp:%Y%m%d_%H%M%S}.{0}", "image_{camera_id}_{tod}.jpg"],
        ["invalid name with spaces.jpg", "image_{unknown_key}.jpg", ""],
    ),
    # FILETRANSFER__REMOTE_METADATA_NAME: regex + format template
    (
        forms.FILETRANSFER__REMOTE_METADATA_NAME_validator,
        ["metadata.json", "metadata_{ts}_{timeofday}.json", "meta_{timestamp:%Y%m%d}.json"],
        ["metadata with spaces.json", "meta_{unknown_key}.json", ""],
    ),
    # FILETRANSFER__REMOTE_FOLDER: regex + no // + no trailing / + format template
    (
        forms.FILETRANSFER__REMOTE_FOLDER_validator,
        ["/allsky/images", "~/allsky/{day_date}", "/remote/path/{camera_uuid}/{timeofday}"],
        ["/allsky/images/", "/allsky//images", "/allsky/{unknown_key}", "/allsky/images$", ""],
    ),
    # FILETRANSFER__UPLOAD_IMAGE: int, >= 0
    (
        forms.FILETRANSFER__UPLOAD_IMAGE_validator,
        [0, 1, 10, 100],
        [-1, -10, "1", 1.5],
    ),
    (
        forms.SYNCAPI__UPLOAD_IMAGE_validator,
        [0, 1, 10, 100],
        [-1, -10, "1", 1.5],
    ),

    # --- Group 33: MQTT ---
    (
        forms.MQTTPUBLISH__HOST_validator,
        ["", "localhost", "mqtt.broker.org", "192.168.1.50", "[fe80::1]"],
        ["broker host", "mqtt#broker", "bad$host"],
    ),
    (
        forms.MQTTPUBLISH__PORT_validator,
        [1, 1883, 8883, 65535],
        [0, -1, 65536, 70000, "string", 1883.5],
    ),
    (
        forms.MQTTPUBLISH__USERNAME_validator,
        ["", "admin", "user@domain.com", "mqtt_user-1"],
        ["user name", "user\\name", "user$name"],
    ),
    (
        forms.MQTTPUBLISH__PASSWORD_validator,
        ["password123", "", None, 123],
        [],
    ),
    # MQTTPUBLISH__BASE_TOPIC: regex + no leading/trailing slash
    (
        forms.MQTTPUBLISH__BASE_TOPIC_validator,
        ["indi-allsky/sensor", "allsky_base", "telemetry/v1"],
        ["/leading/slash", "trailing/slash/", "invalid topic spaces", ""],
    ),
    (
        forms.MQTTPUBLISH__TOPIC_validator,
        ["sensors/temperature", "camera_status", "data"],
        ["/leading/slash", "trailing/slash/"],
    ),
    # MQTTPUBLISH__QOS: int, in (0, 1, 2)
    (
        forms.MQTTPUBLISH__QOS_validator,
        [0, 1, 2],
        [-1, 3, 4, "1", 1.0],
    ),

    # --- Group 34: SyncAPI ---
    (
        forms.SYNCAPI__USERNAME_validator,
        ["", "sync_user", "admin@domain.com", "user-1"],
        ["user name", "user\\name", "user$name"],
    ),
    (
        forms.SYNCAPI__APIKEY_validator,
        ["apikey12345", "", None, 123],
        [],
    ),
    (
        forms.SYNCAPI__TIMEOUT_validator,
        [1, 600, 1200],
        [0, -1, 1201],
    ),
    # SYNCAPI__BASEURL: https only, no trailing /, no localhost
    (
        forms.SYNCAPI__BASEURL_validator,
        ["https://api.allsky.example.com", "https://remote.server.org:8443/api"],
        ["http://api.allsky.example.com", "https://api.allsky.example.com/", "https://localhost/api", "https://127.0.0.1/api", "not_a_url"],
    ),

    # --- Group 35: S3 Upload ---
    (
        forms.S3UPLOAD__ACCESS_KEY_validator,
        ["", "AKIAIOSFODNN7EXAMPLE", "minioadmin"],
        ["invalid access key!", "key-with-dashes", "key@123"],
    ),
    (
        forms.S3UPLOAD__SECRET_KEY_validator,
        ["", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "secret+key/123"],
        ["secret key with spaces", "key@#$"],
    ),
    (
        forms.S3UPLOAD__ENDPOINT_URL_validator,
        ["", "https://s3.amazonaws.com", "http://minio.local:9000"],
        ["not_a_url_no_scheme"],
    ),
    (
        forms.S3UPLOAD__HOST_validator,
        ["s3.amazonaws.com", "minio_docker-host", "192.168.1.1"],
        ["", "host with spaces", "host#name"],
    ),
    (
        forms.S3UPLOAD__PORT_validator,
        [0, 443, 9000, 65535],
        [-1, 65536, "443", 443.5],
    ),
    (
        forms.S3UPLOAD__REGION_validator,
        ["", "us-east-1", "eu-central-1", "ap-southeast-2"],
        ["us_east_1", "region with spaces", "us-east-1!"],
    ),
    (
        forms.S3UPLOAD__BUCKET_validator,
        ["my-allsky-bucket", "bucket.name.123", "bucket123"],
        ["", "bucket_with_underscore", "bucket with spaces", "bucket#name"],
    ),
    (
        forms.S3UPLOAD__NAMESPACE_validator,
        ["", "my-namespace", "namespace01"],
        ["invalid_namespace", "namespace with spaces", "namespace@"],
    ),
    # S3UPLOAD__URL_TEMPLATE: regex + no trailing / + format template
    (
        forms.S3UPLOAD__URL_TEMPLATE_validator,
        ["https://{bucket}.s3.{region}.amazonaws.com", "https://{host}/{bucket}", "http://{namespace}.example.com/{bucket}"],
        ["https://{bucket}.s3.amazonaws.com/", "https://{invalid_key}.s3.amazonaws.com", "url with spaces", ""],
    ),
    (
        forms.S3UPLOAD__ACL_validator,
        ["", "public-read", "private", "authenticated-read"],
        ["public_read", "invalid acl!", "acl with space"],
    ),
    (
        forms.S3UPLOAD__STORAGE_CLASS_validator,
        ["", "STANDARD", "STANDARD-IA", "GLACIER"],
        ["STANDARD_IA", "storage class with space", "CLASS#1"],
    ),
    (
        forms.S3UPLOAD__TIMEOUT_validator,
        [1, 600, 1200],
        [0, -1, 1201],
    ),

    # --- Group 36: Pycurl Camera ---
    (
        forms.PYCURL_CAMERA__USERNAME_validator,
        ["", "cam_admin", "domain\\user", "user@domain.com", "user name"],
        ["user$name", "user#name", "user!name"],
    ),
    (
        forms.PYCURL_CAMERA__PASSWORD_validator,
        ["password123", "", None, 123],
        [],
    ),
    (
        forms.PYCURL_CAMERA__URL_validator,
        ["", "http://192.168.1.50/capture.jpg", "rtsp://camera.local/stream"],
        ["missing_scheme_url.com"],
    ),

    # --- Group 37: ADSB ---
    (
        forms.ADSB__USERNAME_validator,
        ["", "adsb_user", "domain\\user", "user@domain.com", "user name"],
        ["user$name", "user#name", "user!name"],
    ),
    (
        forms.ADSB__PASSWORD_validator,
        ["password123", "", None, 123],
        [],
    ),
    (
        forms.ADSB__DUMP1090_URL_validator,
        ["", "http://localhost:8080/data/aircraft.json", "https://adsb.local/data.json"],
        ["no_scheme_url", "not_a_url"],
    ),

    # --- Group 38: Accumulator ---
    (
        forms.ACCUM_CAMERA__SUB_EXPOSURE_MAX_validator,
        [1.0, 30.0, 60.0, 1, 60],
        [0.99, 0.0, -1.0, 60.01, 70.0, "string"],
    ),

    # --- Group 39: YouTube ---
    # YOUTUBE__TITLE_TEMPLATE: format template
    (
        forms.YOUTUBE__TITLE_TEMPLATE_validator,
        ["Allsky {day_date} {timeofday}", "Timelapse - {asset_label}", "Static Title"],
        ["Title {invalid_key}"],
    ),
    # YOUTUBE__DESCRIPTION_TEMPLATE: empty OK, format template
    (
        forms.YOUTUBE__DESCRIPTION_TEMPLATE_validator,
        ["", "Recorded on {day_date} during {timeofday}", "Description text"],
        ["Recorded on {invalid_key}"],
    ),
    # YOUTUBE__CATEGORY: int only
    (
        forms.YOUTUBE__CATEGORY_validator,
        [22, 27, 28, 1, 0],
        ["28", 28.5],
    ),
    # YOUTUBE__TAGS_STR: empty or any string (no-op)
    (
        forms.YOUTUBE__TAGS_STR_validator,
        ["astronomy, allsky, nightsky", "", "tag1, tag2"],
        [],
    ),

    # --- Group 40: FITS Header ---
    # FITSHEADER_KEY: regex ^[a-zA-Z0-9\-]+$, len <= 8
    (
        forms.FITSHEADER_KEY_validator,
        ["SIMPLE", "BITPIX", "NAXIS1", "A", "12345678"],
        ["TOOLONGKEY", "KEY WITH SPACES", "KEY#1", ""],
    ),

    # --- Group 41: Libcamera ---
    # LIBCAMERA__CAMERA_ID: int(field.data), 0..4
    (
        forms.LIBCAMERA__CAMERA_ID_validator,
        [0, 2, 4, "0", "4"],
        [-1, 5, "5", "-1", "abc"],
    ),
    # LIBCAMERA__EXTRA_OPTIONS: empty OK, else regex + no leading/trailing/double spaces
    (
        forms.LIBCAMERA__EXTRA_OPTIONS_validator,
        ["", "--denoise cdn_off", "--gain 1.5 --shutter 1000", "-v"],
        [" --denoise cdn_off", "--denoise cdn_off ", "--gain  1.5"],
    ),

    # --- Group 42: Test Camera ---
    (
        forms.TEST_CAMERA__WIDTH_validator,
        [100, 1920, 4000],
        [99, 0, -1, 100.0, "1920"],
    ),
    (
        forms.TEST_CAMERA__HEIGHT_validator,
        [100, 1080, 3000],
        [99, 0, -1, 100.0, "1080"],
    ),
    (
        forms.TEST_CAMERA__IMAGE_CIRCLE_DIAMETER_validator,
        [0, 1000, 2000],
        [-1, -100, 0.0, 1000.0, "1000"],
    ),
    (
        forms.TEST_CAMERA__IMAGE_CIRCLE_OFFSET_validator,
        [-100, 0, 100],
        [0.0, 10.5, "0"],
    ),
    (
        forms.TEST_CAMERA__ROTATING_STAR_COUNT_validator,
        [100, 500, 1000],
        [99, 0, -1, 100.0, "500"],
    ),
    # ROTATING_STAR_FACTOR: (int, float), >0 (strict)
    (
        forms.TEST_CAMERA__ROTATING_STAR_FACTOR_validator,
        [0.001, 1.0, 5, 10.5],
        [0.0, 0, -0.1, -1.0, "1.0"],
    ),
    (
        forms.TEST_CAMERA__BUBBLE_COUNT_validator,
        [10, 50, 100],
        [9, 0, -1, 10.0, "50"],
    ),

    # --- Group 43: VirtualSky ---
    (
        forms.VIRTUALSKY__MAGNITUDE_validator,
        [-2.5, 0.0, 6.0, 10],
        ["6.0", "string"],
    ),
    (
        forms.VIRTUALSKY__IMAGE_CIRCLE_DIAMETER_validator,
        [0, 1000, 2000],
        [-1, -100, 0.0, 1000.0, "1000"],
    ),
    (
        forms.VIRTUALSKY__LATITUDE_OFFSET_validator,
        [-90.0, 0.0, 45.5, 90.0, 0],
        ["0.0", "string"],
    ),
    (
        forms.VIRTUALSKY__LONGITUDE_OFFSET_validator,
        [-180.0, 0.0, 90.5, 180.0, 0],
        ["0.0", "string"],
    ),
    (
        forms.VIRTUALSKY__OFFSET_X_validator,
        [-100, 0, 100],
        [0.0, 10.5, "0"],
    ),
    (
        forms.VIRTUALSKY__OFFSET_Y_validator,
        [-100, 0, 100],
        [0.0, 10.5, "0"],
    ),

    # --- Group 44: Circular Display ---
    (
        forms.CIRCULAR_DISPLAY__IMAGE_CIRCLE_DIAMETER_validator,
        [100, 500, 1000],
        [99, 0, -1, 100.0, "500"],
    ),

    # --- Group 45: Dew Heater ---
    (
        forms.DEW_HEATER__LEVEL_validator,
        [0, 50, 100],
        [-1, 101, 50.0, "50"],
    ),
    # DEW_HEATER__THOLD_DIFF: int(field.data) must succeed
    (
        forms.DEW_HEATER__THOLD_DIFF_validator,
        [-10, 0, 10, "5"],
        ["abc", "1.5", "invalid"],
    ),
    # DEW_HEATER__MANUAL_TARGET: (int, float) only
    (
        forms.DEW_HEATER__MANUAL_TARGET_validator,
        [-10.0, 0.0, 25.5, 30],
        ["25.5", "string"],
    ),
    # DEW_HEATER__HOLD_SECONDS: int, 0..600
    (
        forms.DEW_HEATER__HOLD_SECONDS_validator,
        [0, 300, 600],
        [-1, 601, 100.0, "300"],
    ),

    # --- Group 46: PWM & Fan ---
    (
        forms.PWM_FREQUENCY_validator,
        [1, 1000, 10000],
        [0, -1, 10001, 100.0, "1000"],
    ),
    (
        forms.FAN__LEVEL_validator,
        [0, 50, 100],
        [-1, 101, 50.0, "50"],
    ),
    (
        forms.FAN__THOLD_DIFF_validator,
        [-10, 0, 10, "5"],
        ["abc", "1.5", "invalid"],
    ),
    (
        forms.FAN__HOLD_SECONDS_validator,
        [0, 300, 600],
        [-1, 601, 100.0, "300"],
    ),
    # FAN__TARGET: (int, float) only
    (
        forms.FAN__TARGET_validator,
        [-10.0, 0.0, 25.5, 30],
        ["25.5", "string"],
    ),

    # --- Group 47: Sensor Labels & API Keys (no-op) ---
    (
        forms.TEMP_SENSOR__LABEL_validator,
        ["Sensor 1", "Ambient", "", 123],
        [],
    ),
    (
        forms.TEMP_SENSOR__OPENWEATHERMAP_APIKEY_validator,
        ["abcdef123456", ""],
        [],
    ),
    (
        forms.TEMP_SENSOR__WUNDERGROUND_APIKEY_validator,
        ["abcdef123456", ""],
        [],
    ),
    (
        forms.TEMP_SENSOR__ASTROSPHERIC_APIKEY_validator,
        ["abcdef123456", ""],
        [],
    ),
    (
        forms.TEMP_SENSOR__AMBIENTWEATHER_APIKEY_validator,
        ["abcdef123456", ""],
        [],
    ),
    (
        forms.TEMP_SENSOR__AMBIENTWEATHER_APPLICATIONKEY_validator,
        ["abcdef123456", ""],
        [],
    ),
    (
        forms.TEMP_SENSOR__ECOWITT_APIKEY_validator,
        ["abcdef123456", ""],
        [],
    ),
    (
        forms.TEMP_SENSOR__ECOWITT_APPLICATIONKEY_validator,
        ["abcdef123456", ""],
        [],
    ),

    # --- Group 48: Sensor Templates & I2C ---
    # TEMP_SENSOR__TITLE_TEMPLATE: format template with {name}, {label}, {probe}
    (
        forms.TEMP_SENSOR__TITLE_TEMPLATE_validator,
        ["{name} - {label}", "Sensor {probe}", "Static Title", ""],
        ["{invalid_key}", "{extra}"],
    ),
    # I2C_ADDRESS: int(field.data, 16), 0..127
    (
        forms.I2C_ADDRESS_validator,
        ["0x00", "0x40", "0x7f", "0x7F", "0", "7f"],
        ["0x80", "0x100", "invalid_hex"],
    ),
    # MAC address: regex with colons
    (
        forms.TEMP_SENSOR__MACADDRESS_validator,
        ["00:11:22:33:44:55", "AA:BB:CC:DD:EE:FF", "a1:b2:c3:d4:e5:f6", ""],
        ["00:11:22:33:44", "00-11-22-33-44-55", "00:11:22:33:44:55:66", "GG:11:22:33:44:55"],
    ),

    # --- Group 49: Sensor-Specific Settings ---
    # TSL2561_GAIN: int(field.data), 0..1
    (
        forms.TEMP_SENSOR__TSL2561_GAIN_validator,
        [0, 1, "0", "1"],
        [-1, 2, "abc"],
    ),
    # TSL2561_INT: int(field.data), 0..2
    (
        forms.TEMP_SENSOR__TSL2561_INT_validator,
        [0, 1, 2, "0", "2"],
        [-1, 3, "abc"],
    ),
    # AS3935_NOISE_LEVEL: int, 1..7
    (
        forms.TEMP_SENSOR__AS3935_NOISE_LEVEL_validator,
        [1, 4, 7],
        [0, 8, -1, 4.0, "4"],
    ),
    # AS3935_SPIKE_REJECTION: int, 1..11
    (
        forms.TEMP_SENSOR__AS3935_SPIKE_REJECTION_validator,
        [1, 6, 11],
        [0, 12, -1, 6.0, "6"],
    ),

    # --- Group 50: Health Check ---
    # DISK_USAGE: (int, float), 0..101
    (
        forms.HEALTHCHECK__DISK_USAGE_validator,
        [0, 0.0, 50.5, 101, 101.0],
        [-0.1, -1, 101.1, 102, "50"],
    ),
    (
        forms.HEALTHCHECK__SWAP_USAGE_validator,
        [0, 0.0, 50.5, 101, 101.0],
        [-0.1, -1, 101.1, 102, "50"],
    ),

    # --- Group 51: ADSB Extended ---
    # ADSB__ALT_DEG_MIN: <5 invalid, >90 invalid
    (
        forms.ADSB__ALT_DEG_MIN_validator,
        [5, 5.0, 45.0, 90, 90.0],
        [4.9, 4, 90.1, 91, "45"],
    ),
    # ADSB__IMAGE_LABEL_TEMPLATE_PREFIX: no-op (pass)
    (
        forms.ADSB__IMAGE_LABEL_TEMPLATE_PREFIX_validator,
        ["ADSB: ", "", 123],
        [],
    ),
    # ADSB__AIRCRAFT_LABEL_TEMPLATE: format template
    (
        forms.ADSB__AIRCRAFT_LABEL_TEMPLATE_validator,
        ["{flight} {alt:.1f} {az:.1f}", "{id} {squawk} {hex}", "Plane: {flight}", ""],
        ["{unknown_placeholder}", "{flight} {speed}"],
    ),
    # ADSB__LABEL_LIMIT: int, 1..20
    (
        forms.ADSB__LABEL_LIMIT_validator,
        [1, 10, 20],
        [0, -1, 21, 10.0, "10"],
    ),

    # --- Group 52: Satellite Tracking ---
    (
        forms.SATELLITE_TRACK__ALT_DEG_MIN_validator,
        [0, 0.0, 45.0, 90, 90.0],
        [-0.1, -1, 90.1, 91, "45"],
    ),
    (
        forms.SATELLITE_TRACK__IMAGE_LABEL_TEMPLATE_PREFIX_validator,
        ["SAT: ", "", 123],
        [],
    ),
    (
        forms.SATELLITE_TRACK__SAT_LABEL_TEMPLATE_validator,
        ["{title} {alt:.1f} {az:.1f}", "{title} (mag: {mag:.1f})", "Sat: {title}", ""],
        ["{unknown_placeholder}", "{title} {speed}"],
    ),
    (
        forms.SATELLITE_TRACK__LABEL_LIMIT_validator,
        [1, 10, 20],
        [0, -1, 21, 10.0, "10"],
    ),

    # --- Group 53: INDI Config (JSON) ---
    (
        forms.INDI_CONFIG_DEFAULTS_validator,
        [
            "{}",
            '{"PROPERTIES": {"prop1": {"val": 1}}, "TEXT": {"txt1": {"val": "a"}}, "SWITCHES": {"sw1": {"on": ["elem1"]}}}',
            '{"#comment": "ignore"}',
        ],
        [
            "not json",
            '{"INVALID_KEY": {}}',
            '{"SWITCHES": {"sw1": {"invalid_state": []}}}',
            '{"SWITCHES": {"sw1": {"on": "not a list"}}}',
        ],
    ),
    (
        forms.INDI_CONFIG_DAY_validator,
        [
            "{}",
            '{"PROPERTIES": {"prop1": {"val": 1}}}',
            '{"#comment": "ignore"}',
        ],
        [
            "not json",
            '{"INVALID_KEY": {}}',
        ],
    ),

    # --- Group 54: AllskyMap ---
    (
        forms.ALLSKYMAP__INTERVAL_validator,
        [1, 10, 60, "5"],
        [0, -1, "0", "not_a_number"],
    ),

    # --- Group 55: Login & User ---
    (
        forms.LOGIN__USERNAME_validator,
        ["admin", "user@example.com", "user-name.01"],
        ["user name", "user$name", "user!", ""],
    ),
    (
        forms.USER__NAME_validator,
        ["Admin User", "John Doe", ""],
        [],
    ),
    (
        forms.USER__EMAIL_validator,
        ["user@example.com", "admin@domain.co.uk", "a@b.c"],
        ["invalid_email", "user@", "@domain.com"],
    ),
    (
        forms.USER__NEW_PASSWORD_validator,
        ["12345678", "a_very_long_password_123", ""],
        ["1234567", "short", "1"],
    ),

    # --- Group 56: CUSTOM_CHART_MIN (no form needed) ---
    (
        forms.CUSTOM_CHART_MIN_validator,
        [-50.0, 0.0, 100, 25.5],
        ["100", "string"],
    ),
]


# ====================================================================
# Parametrized test runner — main
# ====================================================================
@pytest.mark.parametrize("validator_fn,valid_values,invalid_values", VALIDATOR_TEST_CASES)
def test_validators_parameterized(validator_fn, valid_values, invalid_values):
    """Parametrized test executing both valid and invalid boundary cases for each validator."""
    # Test valid inputs
    for valid_val in valid_values:
        validator_fn(None, DummyField(valid_val))

    # Test invalid inputs
    for invalid_val in invalid_values:
        with pytest.raises(ValidationError):
            validator_fn(None, DummyField(invalid_val))


# ====================================================================
# Validators requiring form.ALLSKYMAP__ENABLE (special form attributes)
# ====================================================================
class TestAllskyMapValidators:
    """ALLSKYMAP__API_URL and ALLSKYMAP__API_KEY depend on form.ALLSKYMAP__ENABLE.data."""

    def test_api_url_when_disabled(self):
        form = _make_form(ALLSKYMAP__ENABLE=DummyField(False))
        # When disabled, empty URL should be fine
        forms.ALLSKYMAP__API_URL_validator(form, DummyField(""))

    def test_api_url_valid_when_enabled(self):
        form = _make_form(ALLSKYMAP__ENABLE=DummyField(True))
        forms.ALLSKYMAP__API_URL_validator(form, DummyField("https://allsky.example.com/api"))

    def test_api_url_empty_when_enabled(self):
        form = _make_form(ALLSKYMAP__ENABLE=DummyField(True))
        with pytest.raises(ValidationError):
            forms.ALLSKYMAP__API_URL_validator(form, DummyField(""))

    def test_api_url_invalid_scheme(self):
        form = _make_form(ALLSKYMAP__ENABLE=DummyField(True))
        with pytest.raises(ValidationError):
            forms.ALLSKYMAP__API_URL_validator(form, DummyField("ftp://allsky.example.com"))

    def test_api_key_when_disabled(self):
        form = _make_form(ALLSKYMAP__ENABLE=DummyField(False))
        forms.ALLSKYMAP__API_KEY_validator(form, DummyField(""))

    def test_api_key_valid_when_enabled(self):
        form = _make_form(ALLSKYMAP__ENABLE=DummyField(True))
        forms.ALLSKYMAP__API_KEY_validator(form, DummyField("my-api-key-123"))

    def test_api_key_empty_when_enabled(self):
        form = _make_form(ALLSKYMAP__ENABLE=DummyField(True))
        with pytest.raises(ValidationError):
            forms.ALLSKYMAP__API_KEY_validator(form, DummyField(""))


# ====================================================================
# File-path validators that need real temporary files / scripts
# ====================================================================
class TestFilePathValidators:
    """Validators that check file existence on disk."""

    def test_filetransfer_private_key_empty(self):
        forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField(""))

    def test_filetransfer_private_key_valid_file(self):
        forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField("/etc/passwd"))

    def test_filetransfer_private_key_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField("/nonexistent/id_rsa"))

    def test_filetransfer_private_key_invalid_regex(self):
        with pytest.raises(ValidationError):
            forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField("invalid key path with spaces"))

    def test_filetransfer_private_key_directory(self):
        with pytest.raises(ValidationError):
            forms.FILETRANSFER__PRIVATE_KEY_validator(None, DummyField("/etc"))

    def test_filetransfer_public_key_empty(self):
        forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField(""))

    def test_filetransfer_public_key_valid_file(self):
        forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField("/etc/passwd"))

    def test_filetransfer_public_key_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField("/nonexistent/id_rsa.pub"))

    def test_filetransfer_public_key_directory(self):
        with pytest.raises(ValidationError):
            forms.FILETRANSFER__PUBLIC_KEY_validator(None, DummyField("/etc"))

    def test_s3upload_creds_file_empty(self):
        forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField(""))

    def test_s3upload_creds_file_valid(self):
        forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField("/etc/passwd"))

    def test_s3upload_creds_file_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField("/nonexistent/creds.json"))

    def test_s3upload_creds_file_directory(self):
        with pytest.raises(ValidationError):
            forms.S3UPLOAD__CREDS_FILE_validator(None, DummyField("/etc"))

    def test_youtube_secrets_file_empty(self):
        forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField(""))

    def test_youtube_secrets_file_valid(self):
        forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField("/etc/passwd"))

    def test_youtube_secrets_file_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField("/nonexistent/secrets.json"))

    def test_youtube_secrets_file_directory(self):
        with pytest.raises(ValidationError):
            forms.YOUTUBE__SECRETS_FILE_validator(None, DummyField("/etc"))


class TestScriptValidator:
    """SCRIPT_validator checks existence, file type, non-empty, readable, executable."""

    def test_script_empty(self):
        forms.SCRIPT_validator(None, DummyField(""))

    def test_script_valid(self):
        # /bin/sh is typically a valid executable file
        forms.SCRIPT_validator(None, DummyField("/bin/sh"))

    def test_script_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.SCRIPT_validator(None, DummyField("/nonexistent/path/script.sh"))

    def test_script_directory(self):
        with pytest.raises(ValidationError):
            forms.SCRIPT_validator(None, DummyField("/tmp"))

    def test_script_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('')  # empty file
            tmp_path = f.name
        try:
            os.chmod(tmp_path, stat.S_IRWXU)
            with pytest.raises(ValidationError):
                forms.SCRIPT_validator(None, DummyField(tmp_path))
        finally:
            os.unlink(tmp_path)

    def test_script_not_executable(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('#!/bin/sh\necho hello\n')
            tmp_path = f.name
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # readable, not executable
            with pytest.raises(ValidationError):
                forms.SCRIPT_validator(None, DummyField(tmp_path))
        finally:
            os.unlink(tmp_path)


class TestWebExtraTextValidator:
    """WEB_EXTRA_TEXT_validator checks file existence and size."""

    def test_empty(self):
        forms.WEB_EXTRA_TEXT_validator(None, DummyField(""))

    def test_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.WEB_EXTRA_TEXT_validator(None, DummyField("/nonexistent_file_xyz_123.txt"))

    def test_invalid_chars(self):
        with pytest.raises(ValidationError):
            forms.WEB_EXTRA_TEXT_validator(None, DummyField("/tmp/invalid$file.txt"))

    def test_directory(self):
        with pytest.raises(ValidationError):
            forms.WEB_EXTRA_TEXT_validator(None, DummyField("/tmp"))

    def test_valid_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir='/tmp') as f:
            f.write('test content')
            tmp_path = f.name
        try:
            forms.WEB_EXTRA_TEXT_validator(None, DummyField(tmp_path))
        finally:
            os.unlink(tmp_path)


class TestImageExtraTextValidator:
    """IMAGE_EXTRA_TEXT_validator — similar to WEB_EXTRA_TEXT."""

    def test_empty(self):
        forms.IMAGE_EXTRA_TEXT_validator(None, DummyField(""))

    def test_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.IMAGE_EXTRA_TEXT_validator(None, DummyField("/tmp/non_existent_file_xyz_123.txt"))

    def test_invalid_chars(self):
        with pytest.raises(ValidationError):
            forms.IMAGE_EXTRA_TEXT_validator(None, DummyField("invalid/path/with/$/characters"))

    def test_directory(self):
        with pytest.raises(ValidationError):
            forms.IMAGE_EXTRA_TEXT_validator(None, DummyField("/tmp"))


class TestFolderValidators:
    """VARLIB_FOLDER, IMAGE_FOLDER, IMAGE_EXPORT_FOLDER validators."""

    def test_varlib_folder_valid(self):
        forms.VARLIB_FOLDER_validator(None, DummyField("/tmp"))

    def test_varlib_folder_trailing_slash(self):
        with pytest.raises(ValidationError):
            forms.VARLIB_FOLDER_validator(None, DummyField("/tmp/"))

    def test_varlib_folder_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.VARLIB_FOLDER_validator(None, DummyField("/nonexistent_folder_xyz_123"))

    def test_varlib_folder_invalid_chars(self):
        with pytest.raises(ValidationError):
            forms.VARLIB_FOLDER_validator(None, DummyField("/tmp/bad folder"))

    def test_image_folder_valid(self):
        forms.IMAGE_FOLDER_validator(None, DummyField("/tmp"))

    def test_image_folder_trailing_slash(self):
        with pytest.raises(ValidationError):
            forms.IMAGE_FOLDER_validator(None, DummyField("/tmp/"))

    def test_image_export_folder_valid(self):
        forms.IMAGE_EXPORT_FOLDER_validator(None, DummyField("/tmp"))

    def test_image_export_folder_trailing_slash(self):
        with pytest.raises(ValidationError):
            forms.IMAGE_EXPORT_FOLDER_validator(None, DummyField("/tmp/"))


class TestPilFontCustomValidator:
    """TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator checks font file validity."""

    def test_empty(self):
        forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField(""))

    def test_nonexistent(self):
        with pytest.raises(ValidationError):
            forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField("/nonexistent/font.ttf"))

    def test_directory(self):
        with pytest.raises(ValidationError):
            forms.TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator(None, DummyField("/tmp"))
