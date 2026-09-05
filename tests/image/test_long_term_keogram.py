from datetime import datetime, timedelta
import numpy as np
import pytest

from indi_allsky.longTermKeogram import LongTermKeogramGenerator
from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbLongTermKeogramTable
from indi_allsky.flask import db


def test_long_term_keogram_generator(app):
    with app.app_context():
        # Setup test camera
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
