import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.allsky import IndiAllSky
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask import db


def test_indi_allsky_initialization(app, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='Main Allsky Cam',
                uuid='cam-allsky-1',
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
            'UPLOAD_WORKERS': 1,
        }

        with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
            mock_cfg_inst = MagicMock()
            mock_cfg_inst.config = mock_config
            mock_cfg_inst.config_id = 1
            mock_cfg_inst.config_level = 1
            mock_cfg_cls.return_value = mock_cfg_inst

            with patch('indi_allsky.allsky.__config_level__', 1):
                allsky = IndiAllSky()

                assert allsky.name == 'Main'
                assert allsky.pid_file == tmp_path / 'indi-allsky.pid'

                # Test signal handlers
                allsky.sighup_handler_main(signal.SIGHUP, None)
                assert allsky._reload is True

                allsky.sigterm_handler_main(signal.SIGTERM, None)
                assert allsky._shutdown is True
                assert allsky._terminate is True

                allsky.sigint_handler_main(signal.SIGINT, None)
                assert allsky._shutdown is True

                # Test pid_file property setter
                custom_pid = tmp_path / 'custom.pid'
                allsky.pid_file = custom_pid
                assert allsky.pid_file == custom_pid
