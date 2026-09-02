import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.darks import IndiAllSkyDarks
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask import db


def test_indi_allsky_darks_properties(app, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='Darks Cam',
                uuid='cam-darks-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)
            db.session.commit()

        mock_config = {
            'LOCATION_LATITUDE': -34.9285,
            'LOCATION_LONGITUDE': 138.6007,
            'LOCATION_ELEVATION': 50,
            'IMAGE_FOLDER': str(tmp_path),
            'VARLIB_FOLDER': str(tmp_path),
        }

        with patch('indi_allsky.darks.IndiAllSkyConfig') as mock_cfg_cls:
            mock_cfg_inst = MagicMock()
            mock_cfg_inst.config = mock_config
            mock_cfg_inst.config_id = 1
            mock_cfg_inst.config_level = 1
            mock_cfg_cls.return_value = mock_cfg_inst

            darks = IndiAllSkyDarks()

            # Test property getters and setters
            darks.count = 20
            assert darks.count == 20

            darks.gain_list = [10.0, 50.0, 100.0]
            assert darks.gain_list == [100.0, 50.0, 10.0]

            darks.binning = 2
            assert darks.binning == 2

            darks.temp_delta = 3.0
            assert darks.temp_delta == 3.0

            darks.time_delta = 10
            assert darks.time_delta == 10
