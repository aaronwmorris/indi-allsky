from datetime import datetime, timedelta
import numpy as np
import pytest

from indi_allsky.longTermKeogram import LongTermKeogramGenerator
from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbLongTermKeogramTable
from indi_allsky.flask import db


def _get_or_create_cam():
    cam = IndiAllSkyDbCameraTable.query.first()
    if not cam:
        cam = IndiAllSkyDbCameraTable(
            name='LTK Camera',
            uuid='cam-ltk-123',
            latitude=-34.9285,
            longitude=138.6007,
            elevation=50,
            nightSunAlt=-6.0,
        )
        db.session.add(cam)
        db.session.commit()
    return cam


def test_long_term_keogram_generator(app):
    with app.app_context():
        # Setup test camera
        cam = _get_or_create_cam()

        # Add mock keogram data entries
        now = datetime.now()
        start_ts = int(now.timestamp())
        for i in range(10):
            entry = IndiAllSkyDbLongTermKeogramTable(
                ts=start_ts + (i * 60),
                camera_id=cam.id,
                r1=200, g1=100, b1=50,
                r2=180, g2=90, b2=45,
                r3=160, g3=80, b3=40,
                r4=140, g4=70, b4=35,
                r5=120, g5=60, b5=30,
            )
            db.session.add(entry)
        db.session.commit()

        generator = LongTermKeogramGenerator({})
        generator.camera_id = cam.id
        generator.days = 1
        generator.alignment_seconds = 60
        generator.offset_seconds = 0
        generator.period_pixels = 3
        generator.reverse = False
        generator.label = False

        query_start = now - timedelta(hours=1)
        query_end = now + timedelta(hours=1)

        keogram_data = generator.generate(query_start, query_end)
        assert isinstance(keogram_data, np.ndarray)
        assert len(keogram_data.shape) == 3
        assert keogram_data.shape[2] == 3


def test_long_term_keogram_pixel_periods_and_reverse(app):
    with app.app_context():
        cam = _get_or_create_cam()

        now = datetime.now()
        start_ts = int(now.timestamp())
        query_start = now - timedelta(minutes=30)
        query_end = now + timedelta(minutes=30)

        # Add sample data
        for i in range(5):
            entry = IndiAllSkyDbLongTermKeogramTable(
                ts=start_ts + (i * 60),
                camera_id=cam.id,
                r1=200, g1=100, b1=50,
                r2=180, g2=90, b2=45,
                r3=160, g3=80, b3=40,
                r4=140, g4=70, b4=35,
                r5=120, g5=60, b5=30,
            )
            db.session.add(entry)
        db.session.commit()

        # Test period_pixels: 1, 2, 4, 5 and reverse = True
        for p in [1, 2, 4, 5]:
            gen = LongTermKeogramGenerator({})
            gen.camera_id = cam.id
            gen.days = 1
            gen.alignment_seconds = 60
            gen.offset_seconds = 0
            gen.period_pixels = p
            gen.reverse = True
            gen.label = False

            data = gen.generate(query_start, query_end)
            assert isinstance(data, np.ndarray)

        # Test assertions on period_pixels
        with pytest.raises(AssertionError):
            gen.period_pixels = 0
        with pytest.raises(AssertionError):
            gen.period_pixels = 6


def test_long_term_keogram_days_42_and_labels(app):
    with app.app_context():
        cam = _get_or_create_cam()


        font_file = "hack/Hack-Regular.ttf"
        config = {
            'IMAGE_LABEL_SYSTEM': 'pillow',
            'TEXT_PROPERTIES': {
                'FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
                'FONT_AA': 'LINE_AA',
                'FONT_SCALE': 0.8,
                'FONT_THICKNESS': 1,
                'FONT_COLOR': [200, 200, 200],
                'FONT_OUTLINE': True,
                'PIL_FONT_FILE': font_file,
            },
            'LONGTERM_KEOGRAM': {
                'MONTH_LABEL_TEMPLATE': '{month:%B %Y}',
                'PIL_FONT_SIZE': 15,
                'OPENCV_FONT_SCALE': 0.6,
            },
        }

        gen = LongTermKeogramGenerator(config)
        gen.camera_id = cam.id
        gen.days = 42  # Triggers special condition: days == 42
        gen.alignment_seconds = 3600
        gen.offset_seconds = 0
        gen.period_pixels = 2
        gen.label = True

        # Query spanning across months to trigger month label rendering
        q_start = datetime(2026, 1, 30, 12, 0, 0)
        q_end = datetime(2026, 2, 5, 12, 0, 0)

        # Add data across the month boundary
        ts1 = int(q_start.timestamp()) + 3600
        ts2 = int(datetime(2026, 2, 2, 12, 0, 0).timestamp())
        for ts in [ts1, ts2]:
            entry = IndiAllSkyDbLongTermKeogramTable(
                ts=ts,
                camera_id=cam.id,
                r1=150, g1=150, b1=150,
                r2=100, g2=100, b2=100,
                r3=50, g3=50, b3=50,
                r4=20, g4=20, b4=20,
                r5=10, g5=10, b5=10,
            )
            db.session.add(entry)
        db.session.commit()

        # 1. Pillow labels with outline=True
        data_pillow = gen.generate(q_start, q_end)
        assert data_pillow is not None

        # 2. Pillow labels with custom font and outline=False
        gen.config['TEXT_PROPERTIES']['PIL_FONT_FILE'] = 'custom'
        gen.config['TEXT_PROPERTIES']['PIL_FONT_CUSTOM'] = str(gen.font_path.joinpath(font_file))
        gen.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
        data_pillow_custom = gen.generate(q_start, q_end)
        assert data_pillow_custom is not None

        # 3. OpenCV labels with outline=True and outline=False
        gen.config['IMAGE_LABEL_SYSTEM'] = 'opencv'
        gen.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = True
        data_cv = gen.generate(q_start, q_end)
        assert data_cv is not None

        gen.config['TEXT_PROPERTIES']['FONT_OUTLINE'] = False
        data_cv_no_outline = gen.generate(q_start, q_end)
        assert data_cv_no_outline is not None

        # 4. Test dialect == 'mysql' branch
        from unittest.mock import patch
        with patch.object(db.engine.dialect, 'name', 'mysql'):
            data_mysql = gen.generate(q_start, q_end)
            assert data_mysql is not None

