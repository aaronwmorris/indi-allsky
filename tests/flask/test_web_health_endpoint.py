import json

from misc.web_recovery import MARKER


def test_health_probe_works_without_database_tables_or_login(monkeypatch, tmp_path):
    config = tmp_path / 'flask.json'
    config.write_text(json.dumps({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                                  'MIGRATION_FOLDER': str(tmp_path), 'SECRET_KEY': 'test',
                                  'INDI_ALLSKY_AUTH_ALL_VIEWS': True}))
    monkeypatch.setenv('INDI_ALLSKY_FLASK_CONFIG', str(config))
    from indi_allsky.flask import create_app
    client = create_app().test_client()
    with client.session_transaction() as session:
        session['_user_id'] = '23'  # would query the empty DB if the login hook were invoked
    response = client.get('/indi-allsky/healthz')
    assert response.status_code == 200
    assert response.data == MARKER
    assert response.mimetype == 'text/plain'
    assert response.cache_control.no_store
