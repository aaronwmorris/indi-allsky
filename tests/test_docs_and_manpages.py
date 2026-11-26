import json
import os
import tempfile
import unittest

from indi_allsky.flask.docs import (
    load_doc_navigation,
    render_doc_markdown,
    resolve_doc_asset,
    resolve_doc_file,
)
from misc.build_manpages import generate_all_manpages


class TestEmbeddedDocsAndManpages(unittest.TestCase):
    def test_resolve_doc_file_and_traversal_guard(self):
        self.assertIsNotNone(resolve_doc_file('Home'))
        self.assertIsNotNone(resolve_doc_file('Configuration-Reference'))
        self.assertIsNotNone(resolve_doc_file('Configuration-Reference.md'))
        self.assertIsNone(resolve_doc_file('../../indi_allsky/config.py'))
        self.assertIsNone(resolve_doc_file('Does-Not-Exist-Page'))
        self.assertIsNone(resolve_doc_asset('Home.md'))
        self.assertIsNone(resolve_doc_asset('../../flask.json_template'))

    def test_load_doc_navigation(self):
        sections = load_doc_navigation()
        self.assertTrue(len(sections) > 0)
        all_slugs = {item['slug'] for sec in sections for item in sec['items']}
        self.assertIn('Configuration-Reference', all_slugs)

    def test_render_doc_markdown_rewrites_links(self):
        md = (
            '# Title\n\n'
            '> [!IMPORTANT]\n'
            '> HTTPS is required.\n\n'
            'See [Sync](SyncAPI-Setup#sec) and '
            '[Wiki](https://github.com/aaronwmorris/indi-allsky/wiki/VirtualSky#top) and '
            '![img](images/example.png).\n'
        )
        html, _ = render_doc_markdown(
            md,
            url_for_doc=lambda s: f'/indi-allsky/docs/{s}',
            url_for_asset=lambda a: f'/indi-allsky/docs/assets/{a}',
        )
        html_str = str(html)
        self.assertIn('indi-doc-alert-important', html_str)
        self.assertIn('HTTPS is required.', html_str)
        self.assertIn('href="/indi-allsky/docs/SyncAPI-Setup#sec"', html_str)
        self.assertIn('href="/indi-allsky/docs/VirtualSky#top"', html_str)
        self.assertIn('src="/indi-allsky/docs/assets/images/example.png"', html_str)

    def test_flask_docs_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'test.sqlite')
            img_dir = os.path.join(tmpdir, 'images')
            os.makedirs(img_dir, exist_ok=True)
            with open('flask.json_template') as f:
                flask_cfg = json.load(f)
            flask_cfg.update({
                'SECRET_KEY': 'test-secret',
                'PASSWORD_KEY': 'test-password-key-32bytes-padding',
                'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
                'MIGRATION_FOLDER': os.path.abspath('migrations'),
                'INDI_ALLSKY_IMAGE_FOLDER': img_dir,
                'INDI_ALLSKY_DOCROOT': os.path.abspath('indi_allsky/flask/static'),
                'SESSION_COOKIE_SECURE': False,
                'REMEMBER_COOKIE_SECURE': False,
            })
            cfg_path = os.path.join(tmpdir, 'flask.json')
            with open(cfg_path, 'w') as f:
                json.dump(flask_cfg, f)

            old_cfg = os.environ.get('INDI_ALLSKY_FLASK_CONFIG')
            os.environ['INDI_ALLSKY_FLASK_CONFIG'] = cfg_path
            try:
                from indi_allsky.flask import create_app, db
                from indi_allsky.flask.models import IndiAllSkyDbConfigTable, IndiAllSkyDbUserTable

                app = create_app()
                with app.app_context():
                    db.create_all()
                    user = IndiAllSkyDbUserTable(
                        username='admin',
                        password='x',
                        email='admin@localhost',
                        name='Admin',
                        apikey='test',
                        staff=True,
                        admin=True,
                        active=True,
                    )
                    db.session.add(user)
                    db.session.flush()
                    db.session.add(IndiAllSkyDbConfigTable(
                        data={'LOCATION_LATITUDE': 0.0, 'LOCATION_LONGITUDE': 0.0, 'LOCATION_ELEVATION': 0},
                        level='admin',
                        note='test seed',
                        user_id=user.id,
                    ))
                    db.session.commit()

                with app.test_client() as client:
                    res_home = client.get('/indi-allsky/docs')
                    self.assertEqual(res_home.status_code, 200)
                    self.assertIn(b'Documentation', res_home.data)

                    res_cfg = client.get('/indi-allsky/docs/Configuration-Reference')
                    self.assertEqual(res_cfg.status_code, 200)
                    self.assertIn(b'Configuration', res_cfg.data)

                    res_missing = client.get('/indi-allsky/docs/NoSuchPageXYZ')
                    self.assertEqual(res_missing.status_code, 404)

                    res_trav = client.get('/indi-allsky/docs/..%2F..%2Fconfig')
                    self.assertEqual(res_trav.status_code, 404)
            finally:
                if old_cfg is None:
                    os.environ.pop('INDI_ALLSKY_FLASK_CONFIG', None)
                else:
                    os.environ['INDI_ALLSKY_FLASK_CONFIG'] = old_cfg

    def test_manpage_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            generated = generate_all_manpages(tmpdir)
            names = {p.name for p in generated}
            self.assertIn('indi-allsky-ctl.1', names)
            self.assertIn('indi-allsky.7', names)
            self.assertIn('indi-allsky-configuration-reference.7', names)

            ctl_text = (os.path.join(tmpdir, 'man1', 'indi-allsky-ctl.1'))
            with open(ctl_text, encoding='utf-8') as f:
                content = f.read()
            self.assertIn('.TH "INDI-ALLSKY-CTL" "1"', content)
            self.assertIn('.SH COMMANDS', content)
            self.assertIn('backup-db', content)


if __name__ == '__main__':
    unittest.main()
