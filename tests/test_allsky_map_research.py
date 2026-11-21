import json
import logging

import pytest

from indi_allsky import allsky_map


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"status":"ok"}'


@pytest.fixture
def sent(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured['url'] = req.full_url
        captured['payload'] = json.loads(req.data.decode('utf-8'))
        return _FakeResponse()

    monkeypatch.setattr(allsky_map.urllib.request, 'urlopen', fake_urlopen)
    return captured


def _config(**allskymap):
    conf = {
        'API_URL': 'https://allsky-map.example',
        'API_KEY': 'allsky_live_test',
        'UPLOAD_IMAGE': False,
    }
    conf.update(allskymap)
    return {
        'LOCATION_LATITUDE': 51.05,
        'LOCATION_LONGITUDE': -114.07,
        'ALLSKYMAP': conf,
    }


def test_ping_shares_for_research_by_default(sent):
    ok, _ = allsky_map.send_allsky_map_ping(_config(), logging.getLogger(__name__))

    assert ok
    assert sent['url'] == 'https://allsky-map.example/api/ping'
    assert sent['payload']['allowResearch'] is True


@pytest.mark.parametrize('value', [True, False])
def test_ping_sends_configured_research_choice(sent, value):
    ok, _ = allsky_map.send_allsky_map_ping(_config(ALLOW_RESEARCH=value), logging.getLogger(__name__))

    assert ok
    assert sent['payload']['allowResearch'] is value
