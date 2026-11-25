"""The observed skyline requires a stable, aligned and genuinely visible sky."""
from copy import deepcopy

import cv2
import numpy as np
from PIL import Image
import pytest

from indi_allsky import companion_visible_horizon as horizon


def polar_sky():
    alt, az = np.meshgrid(horizon._ALT, horizon._AZ, indexing='ij')
    ground = np.where((az < 20) | (az > 340), 27, 8)
    gray = np.where(alt < ground, 5, 50).astype('uint8')
    return gray, alt, az


def test_ground_connection_uses_north_wrap_and_ignores_floating_cloud():
    gray, alt, az = polar_sky()
    gray[(alt >= 43) & (alt < 53) & (az > 45) & (az < 150)] = 5
    edges, _ = horizon._outline(gray, np.ones_like(gray, bool), np.array([]), np.array([]), 50)
    assert edges[0] == pytest.approx(27, abs=1)
    assert edges[-1] == pytest.approx(27, abs=1)
    assert edges[45] == pytest.approx(8, abs=1)


def test_sensor_crop_and_ambiguous_edges_require_a_star_above_the_clear_floor():
    gray, alt, az = polar_sky()
    valid = alt >= 16
    gray[~valid] = 0
    # A smooth gradient has no physical skyline that can be located reliably.
    gray[:, :90] = np.clip(10 + 1.1*(alt[:, :90] - 16), 10, 50).astype('uint8')
    edges, floors = horizon._outline(gray, valid, np.array([90, 10, 12]), np.array([21, 18, 55]), 50)
    assert np.isnan(edges[45]) and floors[45] == 21  # a star, not the 16-degree crop
    assert np.isnan(edges[5]) and floors[5] == 55  # lower star lies below the clear region
    assert np.isnan(edges[90]) and np.isnan(floors[90])  # no local support


def test_fine_rays_pick_up_narrow_twig_and_sideways_limb_with_sky_beneath():
    # Synthetic angular camera with native pixels twice as dense as output bearings.
    # A 0.5-degree twig, a slanted bough and its nearly horizontal offshoot.
    altitude, azimuth = horizon._BRANCH_ALT, horizon._BRANCH_AZ
    pixels = np.full((len(altitude), 2 * len(azimuth)), 60, dtype=np.uint8)
    pixels[:64] = 8  # real horizon at 8 degrees
    cv2.line(pixels, (720, 60), (720, 160), 9, 2)
    cv2.line(pixels, (720, 130), (770, 182), 9, 2)
    cv2.line(pixels, (770, 182), (814, 185), 9, 2)
    cv2.line(pixels, (828, 209), (900, 212), 9, 3)  # floating dark feature
    # A black text outline connected to land surrounding bright caption ink.
    cv2.line(pixels, (960, 60), (960, 158), 1, 5)
    cv2.line(pixels, (960, 60), (960, 158), 215, 2)
    indexes = np.arange(pixels.size, dtype=np.int32).reshape(pixels.shape)[:, ::2].copy()
    indexes[:175, 515:525] = -1  # sensor crop through unobstructed sky
    tips = horizon._branch_tops(pixels, indexes, 60)
    assert tips[360] == pytest.approx(20, abs=.5)
    assert tips[357] == pytest.approx(8, abs=.5)
    assert tips[375] == pytest.approx(20.25, abs=.5)
    assert tips[399] == pytest.approx(23., abs=.5)
    assert tips[420] == pytest.approx(8, abs=.5)
    assert tips[480] < 9 or np.isnan(tips[480])
    assert np.isnan(tips[520])


def model(stamp=1700000000):
    return dict(id='a'*32, location=[45., 10.], image_size=[400, 400], observed_at=stamp,
                values=dict(AZIMUTH_ANGLE=0., LENS_ALTITUDE=90., POINTING_AZIMUTH=0.,
                            LATITUDE_OFFSET=0., LONGITUDE_OFFSET=0., RADIAL_DISTORTION=0.,
                            IMAGE_CIRCLE_DIAMETER=380, OFFSET_X=0, OFFSET_Y=0, PRECESSION=True))


def draw_land(path, height):
    y, x = np.indices((400, 400))
    radius = np.hypot(x-200, y-200)
    altitude = 90 - np.degrees(2*np.arcsin(np.clip(radius/190 * np.sin(np.pi/4), 0, 1)))
    Image.fromarray(np.where(altitude < height, 6, 60).astype('uint8')).save(path)


def clear_stars(*args, max_sun_altitude):
    assert max_sun_altitude == -12.
    az = np.radians(np.arange(360))
    altitude = np.radians(54.)
    vectors = np.column_stack((np.cos(az)*np.cos(altitude), np.sin(az)*np.cos(altitude),
                               np.full(len(az), np.sin(altitude))))
    return vectors, np.full(360, 54.), np.full(360, 3.), np.ones(360), np.zeros(360), np.full(360, 60.)


def test_confirmed_stationary_land_and_moving_edge(tmp_path, monkeypatch):
    monkeypatch.setattr(horizon, 'frame_star_evidence', clear_stars)
    frames = []
    for number, height in enumerate([17, 17, 40]):
        path = tmp_path / ('capture%d.png' % number)
        draw_land(path, height)
        frames.append((path, model(1700000000 + number*300)))
    report = horizon.measure_horizon(frames[:2])
    assert report['frames'] == 2 and len(report['altitudes']) * report['step_deg'] == 360
    assert min(report['altitudes']) >= 16 and max(report['altitudes']) <= 18
    changed = horizon.measure_horizon(frames)
    assert all(edge is None for edge in changed['altitudes'])
    assert min(changed['image_floor']) >= 53  # mixed silhouettes cannot later be reported as terrain
    assert horizon.measure_horizon([frames[0], frames[0]]) is None
    foreign = deepcopy(frames[1][1])
    foreign['id'] = 'b'*32
    assert horizon.measure_horizon([frames[0], (frames[1][0], foreign)]) is None


def test_repeated_tip_survives_one_faint_frame_but_single_high_edge_stays_unknown(tmp_path, monkeypatch):
    frames = []
    fine = {}
    for number, (twig, cloud) in enumerate([(22., 10.), (22.5, 28.), (12., 10.)]):
        path = tmp_path / str(number)
        path.touch()
        frames.append((path, model(1700000000 + number*300)))
        tips = np.full(len(horizon._BRANCH_AZ), 10.)
        tips[17:19] = twig  # half a degree in azimuth
        tips[55] = cloud
        fine[str(path)] = tips
    monkeypatch.setattr(horizon, '_measure_frame', lambda path, *args: (
        np.full(180, 10.), np.full(180, 40.), fine[path]))
    result = horizon.measure_horizon(frames)
    assert result['altitudes'][16:20] == [10., 22.5, 22.5, 10.]
    assert result['altitudes'][55] is None and result['image_floor'][55] == 40.


def test_crown_is_continuous_across_north_and_wide_gap_and_preserves_branch_tips():
    az = horizon._BRANCH_AZ
    edges = np.full(len(az), np.nan)
    floors = edges.copy()
    for angle, height in [(357, 23), (4, 16), (60, 10), (120, 14), (270, 12)]:
        edges[az == angle] = height
    # Two individually confirmed tips with a one-degree indentation between.
    edges[(az >= 27) & (az <= 33)] = 11
    edges[(az == 29) | (az == 30)] = 26
    edges[az == 80] = 35  # isolated genuine branch
    floors[az == 200] = 8  # star in the wide, unobserved western sector
    result = np.array(horizon._estimated_envelope(edges, floors))
    assert len(result) == len(az) and np.all((result >= 0) & (result <= 90))
    assert np.max(np.abs(result - np.roll(result, 1))) <= 4 * horizon.STEP + .001
    assert 16 <= result[0] <= 23
    assert result[az == 29.5].item() == 26 and result[az == 80].item() == 35
    assert result[az == 200].item() <= 8 and np.all(result[np.isfinite(edges)] >= edges[np.isfinite(edges)])


def test_stars_alone_or_a_single_grounded_tree_do_not_create_a_full_ring():
    edges = np.full(len(horizon._BRANCH_AZ), np.nan)
    floors = np.full_like(edges, 45)
    assert horizon._estimated_envelope(edges, floors) is None
    edges[:40] = 17
    assert horizon._estimated_envelope(edges, floors) is None


def test_one_registered_frame_yields_an_estimate_and_no_claim_of_repeated_edges(tmp_path, monkeypatch):
    monkeypatch.setattr(horizon, 'frame_star_evidence', clear_stars)
    path = tmp_path / 'first.png'
    draw_land(path, 17)
    frame = (path, model())
    profile = horizon.measure_horizon([frame])
    assert profile['quality'] == 'estimated' and profile['frames'] == 1
    assert set(profile['altitudes'] + profile['image_floor']) == {None}
    assert np.allclose(profile['envelope'], 17, atol=1.)
    assert horizon.measure_horizon([frame, frame]) is None
    again = horizon.measure_horizon([frame, (path, model(model()['observed_at'] + 300))])
    assert again['quality'] == 'repeated' and again['frames'] == 2


def test_thumbnail_checks_foreground_across_exposures_weather_and_a_new_obstruction(tmp_path):
    from indi_allsky.companion_target_quality import _sky_positions
    from indi_allsky.lens_solver.catalog import loadCatalog

    def signature(name, seconds, *, tower=False, brighter=False, frost=False, stars=True, cloud=False):
        pose = model(1700000000 + seconds)
        y, x = np.indices((400, 400))
        radius = np.hypot(x-200, y-200)
        alt = 90 - np.degrees(2*np.arcsin(np.clip(radius / 190 * np.sin(np.pi/4), 0, 1)))
        terrain = np.full(alt.shape, 14)
        if tower:
            terrain[(x > 200) & (np.abs(y-200) < .45 * (x-200))] = 32
        clear = alt > terrain
        photo = np.where(clear, 50 + 4*np.sin(x/60), 7.).astype(np.uint8)
        if stars:
            _, _, sx, sy, visible = _sky_positions(
                loadCatalog(mag_limit=4.), *pose['location'], pose['observed_at'], True,
                horizon.projection_values(pose), pose['image_size'])
            for xx, yy in zip(np.rint(sx[visible]).astype(int), np.rint(sy[visible]).astype(int)):
                if 0 <= xx < 400 and 0 <= yy < 400 and clear[yy, xx]:
                    cv2.circle(photo, (xx, yy), 1, 185, -1)
        if brighter:
            photo = np.clip(1.6*photo + 6, 0, 255).astype(np.uint8)
        if cloud:
            # A dark bank near the treetops, with a soft edge and clear sky elsewhere.
            veil = .8*np.exp(-((x-345)/27.)**2 - ((y-182)/47.)**2)
            photo = np.rint(photo*(1 - veil) + 9*veil).astype(np.uint8)
        cv2.putText(photo, name, (4, 15), cv2.FONT_HERSHEY_SIMPLEX, .42, 230, 1)
        if frost:
            photo = cv2.GaussianBlur(photo, (0, 0), 7.)
        path = tmp_path / (name + '.png')
        Image.fromarray(photo).save(path)
        return horizon.horizon_signature(path, pose)

    reference = signature('reference', 0)
    brighter = signature('brighter', 600, brighter=True)
    assert reference is not None and brighter is not None
    assert horizon.significant_horizon_change(reference, brighter) is False
    assert horizon.significant_horizon_change(reference, signature('moving-cloud', 720, cloud=True)) is False
    changed = signature('new-obstruction', 900, tower=True)
    repeat = signature('same-obstruction', 1200, tower=True, brighter=True)
    assert horizon.significant_horizon_change(reference, changed) is True
    assert horizon.significant_horizon_change(reference, repeat) is True
    assert horizon.significant_horizon_change(changed, repeat) is False
    assert signature('overcast', 1500, stars=False) is None
    assert signature('frost', 1800, frost=True) is None
    assert signature('day', 12*3600) is None
    assert horizon.significant_horizon_change(reference, None) is None


def test_missing_archived_image_and_daylight_do_not_supply_horizon(tmp_path, monkeypatch):
    path = tmp_path / 'archive.png'
    frames = [(path, model(1700000000 + n*300)) for n in range(2)]
    assert horizon.measure_horizon(frames) is None
    draw_land(path, 20)
    monkeypatch.setattr(horizon, 'frame_star_evidence', lambda *a, **kw: None)
    assert horizon.measure_horizon(frames) is None
