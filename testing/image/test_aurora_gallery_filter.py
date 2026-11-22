from datetime import datetime
from pathlib import Path
import unittest

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from indi_allsky.flask.forms import (
    DEFAULT_AURORA_MIN,
    IndiAllskyGalleryViewer,
    IndiAllskyImageViewer,
    _apply_aurora_filter,
    normalize_aurora_min,
)
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    db,
)


class TestAuroraGalleryFilter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[2]

    def test_normalize_aurora_min(self):
        self.assertEqual(normalize_aurora_min(None), DEFAULT_AURORA_MIN)
        self.assertEqual(normalize_aurora_min(''), DEFAULT_AURORA_MIN)
        self.assertEqual(normalize_aurora_min('invalid'), DEFAULT_AURORA_MIN)
        self.assertEqual(normalize_aurora_min(0), 1)
        self.assertEqual(normalize_aurora_min(-10), 1)
        self.assertEqual(normalize_aurora_min(150), 100)
        self.assertEqual(normalize_aurora_min('85'), 85)

    def test_apply_aurora_filter_query(self):
        engine = create_engine('sqlite:///:memory:')
        IndiAllSkyDbCameraTable.__table__.create(engine)
        IndiAllSkyDbImageTable.__table__.create(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            camera = IndiAllSkyDbCameraTable(uuid='cam-aurora-test', name='Test Camera')
            session.add(camera)
            session.flush()

            now = datetime(2026, 11, 22, 12, 0, 0)
            for idx, ovation in enumerate((None, 20, 79, 80, 95)):
                img = IndiAllSkyDbImageTable(
                    camera_id=camera.id,
                    filename=f'img_{idx}.jpg',
                    createDate=now,
                    createDate_year=now.year,
                    createDate_month=now.month,
                    createDate_day=now.day,
                    createDate_hour=now.hour,
                    dayDate=now.date(),
                    exposure=1.0,
                    gain=0.0,
                    adu=100.0,
                    ovation_max=ovation,
                )
                session.add(img)
            session.commit()

            base_q = session.query(IndiAllSkyDbImageTable)

            all_rows = _apply_aurora_filter(base_q, 0).all()
            self.assertEqual(len(all_rows), 5)

            filtered_80 = _apply_aurora_filter(base_q, 80).all()
            self.assertEqual(sorted(r.ovation_max for r in filtered_80), [80, 95])

            filtered_20 = _apply_aurora_filter(base_q, 20).all()
            self.assertEqual(sorted(r.ovation_max for r in filtered_20), [20, 79, 80, 95])
        finally:
            session.close()
            engine.dispose()

    def test_viewer_forms_have_aurora_fields(self):
        app = Flask(__name__)
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SECRET_KEY'] = 'test'
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        db.init_app(app)

        with app.app_context():
            for form_cls in (IndiAllskyImageViewer, IndiAllskyGalleryViewer):
                form = form_cls(camera_id=1, aurora_min=80)
                self.assertTrue(hasattr(form, 'FILTER_AURORA'))
                self.assertTrue(hasattr(form, 'FILTER_AURORA_MIN'))
                self.assertEqual(form.aurora_min, 80)

    def test_templates_include_aurora_filter_controls(self):
        for rel_path in (
            'indi_allsky/flask/templates/gallery.html',
            'indi_allsky/flask/templates/imageviewer.html',
        ):
            content = (self.project_root / rel_path).read_text(encoding='utf-8')
            self.assertIn('FILTER_AURORA', content)
            self.assertIn('FILTER_AURORA_MIN', content)


if __name__ == '__main__':
    unittest.main()
