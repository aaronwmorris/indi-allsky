import math

import cv2
import numpy as np
from PIL import Image
import pytest

from indi_allsky import companion_target_quality as quality


TARGETS = [(66.75, 55.466667), (317.95075, 59.985833)]


@pytest.fixture
def model():
    return dict(image_size=[1000, 1000], observed_at=1794685508, location=[52., 12.], values=dict(
        AZIMUTH_ANGLE=0., OFFSET_X=0., OFFSET_Y=0., IMAGE_CIRCLE_DIAMETER=1000.,
        LATITUDE_OFFSET=0., LONGITUDE_OFFSET=0., RADIAL_DISTORTION=0.,
        LENS_ALTITUDE=90., POINTING_AZIMUTH=0., PRECESSION=True))


def artificial_frame(path, model, state):
    size = model['image_size']
    geometry = (*model['location'], model['observed_at'], True, quality.projection_values(model), size)
    _, target, tx, ty, _ = quality._sky_positions(np.array(TARGETS), *geometry)
    stars = quality.loadCatalog(mag_limit=5.5)
    alt, vectors, x, y, visible = quality._sky_positions(stars, *geometry)
    local = vectors @ target[0] >= math.cos(math.radians(quality.FIELD_RADIUS))
    gray = np.full((size[1], size[0]), 35, np.uint8)
    if state == 'thin_cloud':
        cv2.circle(gray, (round(tx[0]), round(ty[0])), 93, 58, -1)
    local_count = 0
    for xx, yy, above, in_image, near in zip(x, y, alt, visible, local):
        if not in_image or above <= 0:
            continue
        if near:
            local_count += 1
            if state == 'obscured' or (state == 'thin_cloud' and local_count % 3):
                continue
        cv2.circle(gray, (round(xx), round(yy)), 1, 220, -1)
    Image.fromarray(gray).save(path)


@pytest.mark.parametrize('state', ['clear', 'thin_cloud', 'obscured'])
def test_conditions_are_local_to_the_target(tmp_path, model, state):
    path = tmp_path / 'test.png'
    artificial_frame(path, model, state)
    result = quality.assess_targets(path, model, TARGETS, night=True, exposure=30, gain=16)
    assert [item['state'] for item in result] == [state, 'clear']
    assert all(item['expected'] >= 6 for item in result)


def test_starless_frame_and_missing_evidence_are_unknown(tmp_path, model):
    path = tmp_path / 'blank.jpg'
    Image.new('L', (1000, 1000), 40).save(path)
    def assess(**overrides):
        inputs = dict(path=path, model=model, coordinates=TARGETS, night=True, exposure=20, gain=0)
        inputs.update(overrides)
        return quality.assess_targets(**inputs)
    for changes in ({}, {'model': None}, {'night': False}, {'path': None}, {'exposure': 0},
                    {'gain': None}, {'model': dict(model, image_size=[800, 600])}):
        result = assess(**changes)
        assert len(result) == 2 and all(item['state'] == 'unknown' for item in result)
    assert 'elsewhere' in assess()[0]['reason']


def test_image_measurements_reused_across_target_requests(tmp_path, model):
    path = tmp_path / 'test.png'
    artificial_frame(path, model, 'clear')
    first = quality._frame_stars.cache_info()
    for target in TARGETS:
        quality.assess_targets(path, model, [target], night=True, exposure=30, gain=16)
    last = quality._frame_stars.cache_info()
    assert last.misses == first.misses + 1 and last.hits == first.hits + 1


def test_moon_glare_and_twilight_are_unknown(tmp_path, model, monkeypatch):
    path = tmp_path / 'test.png'
    artificial_frame(path, model, 'clear')
    _, vectors, _, _, _ = quality._sky_positions(
        np.array(TARGETS), *model['location'], model['observed_at'], True,
        quality.projection_values(model), model['image_size'])
    monkeypatch.setattr(quality, '_lights', lambda location, stamp: (-35., vectors[0]))
    near_moon, away = quality.assess_targets(path, model, TARGETS, night=True, exposure=30, gain=16)
    assert near_moon['state'] == 'unknown' and 'Moon' in near_moon['reason']
    assert away['state'] == 'clear'
    monkeypatch.setattr(quality, '_lights', lambda location, stamp: (-8., None))
    assert all('twilight' in q['reason'] for q in quality.assess_targets(
        path, model, TARGETS, night=True, exposure=30, gain=16))
