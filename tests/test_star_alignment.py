import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from indi_allsky import star_alignment as align


def solution(offset=0.):
    return {'image_size': [1920, 1080], 'values': {'IMAGE_CIRCLE_DIAMETER': 1020, 'AZIMUTH_ANGLE': 0.},
            'location': [52., 13.], 'directions': {key: [x + offset, y] for key, (x, y) in zip(
                align.DIRECTIONS, ((.5, .05), (.2, .5), (.5, .95), (.8, .5)))}}


@pytest.fixture
def station(tmp_path, monkeypatch):
    clock = SimpleNamespace(t=10000.)
    monkeypatch.setattr(align.time, 'time', lambda: clock.t)
    monkeypatch.setattr(align.time, 'monotonic', lambda: clock.t)
    worker = align.StarAlignment({'VARLIB_FOLDER': str(tmp_path)})
    calls = []

    class Process:
        returncode = None
        def poll(self):
            return self.returncode

        def finish(self, result):
            self.stdout = io.BytesIO(json.dumps(result).encode())
            self.returncode = 0

        def kill(self):
            self.finish(None)

        def wait(self, timeout=None):
            assert self.returncode is not None

    def start(command, **kwargs):
        obj = Process()
        request = json.load(kwargs['stdin'])
        calls.append((obj, request))
        assert command[-1] == 'indi_allsky.star_alignment'
        assert kwargs['env']['OPENBLAS_NUM_THREADS'] == '1'
        return obj

    monkeypatch.setattr(align.subprocess, 'Popen', start)

    def frame(seconds=0, night=True, date='Nov 10', camera='camera', site=(52., 13.), size=(1920, 1080)):
        clock.t += seconds
        result = worker.begin_frame(camera, date, night, clock.t, size, site)
        worker.offer_frame(tmp_path / ('frame-%s.jpg' % clock.t))
        return result

    return worker, clock, calls, frame


def test_two_independent_exposures_and_stable_session_identity(station):
    worker, clock, calls, frame = station
    assert frame() is None
    assert frame(1) is None and len(calls) == 1
    calls[0][0].finish(solution())
    assert frame(1) is None and align.read_alignment_status(worker.config, worker.camera) == 'pending'
    frame(27)
    assert len(calls) == 1
    frame(3)
    assert len(calls) == 2
    assert calls[0][1]['path'] != calls[1][1]['path']
    calls[1][0].finish(solution(.001))
    assert frame(1) == solution(.001)['directions']
    identity = worker.solution['id']
    assert align.read_alignment_status(worker.config, worker.camera) == 'aligned'
    frame(align.CHECK_INTERVAL)
    calls[-1][0].finish(solution(.002))
    frame(1)
    assert worker.solution['id'] == identity and worker.solution['directions'] == solution(.001)['directions']
    worker.close()
    assert align.read_alignment_status(worker.config, 'camera') == 'pending'


def test_positive_disagreement_suppresses_stale_labels_before_new_confirmation(station):
    worker, _, calls, frame = station
    frame()
    calls[-1][0].finish(solution())
    frame(1)
    frame(align.CONFIRM_INTERVAL)
    calls[-1][0].finish(solution())
    frame(1)
    first = worker.solution['id']
    frame(align.CHECK_INTERVAL)
    calls[-1][0].finish(solution(.14))
    assert frame(1) is None
    assert align.read_alignment_status(worker.config, worker.camera) == 'pending'
    frame(align.CONFIRM_INTERVAL)
    calls[-1][0].finish(solution(.138))
    assert frame(1) == solution(.138)['directions']
    assert worker.solution['id'] != first


@pytest.mark.parametrize('change', [
    {'site': (49., 13.)}, {'size': (1920, 1920)}, {'camera': 'second'}, {'date': 'Nov 11'},
    {'seconds': 901}
])
def test_reset_discards_candidate_and_inflight_result(station, change):
    worker, _, calls, frame = station
    frame()
    calls[-1][0].finish(solution())
    frame(1)
    frame(align.CONFIRM_INTERVAL)
    calls[-1][0].finish(solution())
    assert frame(**change) is None
    assert worker.solution is None and worker.candidate is None


def test_overcast_retries_and_stale_file_never_launches(station, tmp_path):
    worker, clock, calls, frame = station
    frame()
    calls[-1][0].finish(None)
    frame(1)
    frame(60)
    assert len(calls) == 1
    frame(60)
    assert len(calls) == 2
    calls[-1][0].finish(None)
    frame(1)
    worker.close()
    worker.begin_frame('camera', 'Nov 10', True, clock.t - 3000, (1920, 1080), (52., 13.))
    worker.offer_frame(tmp_path / 'yesterday.jpg')
    assert len(calls) == 2
    frame(night=False)
    assert len(calls) == 2


def test_deadline_and_invalid_location_do_not_interrupt_capture(station):
    worker, _, calls, frame = station
    frame()
    job = calls[0][0]
    frame(align.SOLVE_TIMEOUT + 6)
    assert job.returncode is not None and len(calls) == 1
    assert frame(site=(None, None)) is None
    assert not worker.solution


def test_status_is_camera_scoped_and_expires(station):
    worker, clock, _, frame = station
    frame()
    worker.solution = solution()
    worker._publish(force=True)
    assert align.read_alignment_status(worker.config, 'another') == 'pending'
    assert align.read_alignment_status(worker.config, 'camera') == 'aligned'
    clock.t += worker.max_frame_age + 1
    assert align.read_alignment_status(worker.config, 'camera') == 'pending'


def test_duplicate_archive_path_is_not_an_independent_observation(station):
    worker, clock, calls, frame = station
    frame()
    original = calls[-1][1]['path']
    calls[-1][0].finish(solution())
    frame(1)
    clock.t += 35
    worker.begin_frame('camera', 'Nov 10', True, clock.t, (1920, 1080), (52., 13.))
    worker.offer_frame(Path(original))
    assert len(calls) == 1


def test_real_solver_returns_geographical_directions_from_a_fisheye_exposure(tmp_path):
    import numpy as np
    from tests.test_lens_solver_solve import render_sky_image
    from indi_allsky.lens_solver import projectToPixels
    from indi_allsky.lens_solver.projection import precessCatalog
    from indi_allsky.lens_solver.catalog import loadCatalog
    stamp, lat, lon, size = 1770000000, 40.1, -75.4, 1920
    true = [30., 0., 0., 1650., 12., -15.]
    path = tmp_path / 'sky.png'
    render_sky_image(path, true, size, size, stamp, lat, lon, precessCatalog(loadCatalog(), stamp))
    seed = dict(AZIMUTH_ANGLE=24., LENS_ALTITUDE=90., POINTING_AZIMUTH=0., RADIAL_DISTORTION=0.,
                LATITUDE_OFFSET=0., LONGITUDE_OFFSET=0., IMAGE_CIRCLE_DIAMETER=1600.,
                OFFSET_X=0., OFFSET_Y=0., PRECESSION=True)
    result = align.solve_frame(dict(seed=seed, config={}, timestamp=stamp, location=[lat, lon],
                                   size=[size, size], path=str(path), binning=1, sensor_shape=None))
    assert result is not None and result['location'] == [lat, lon]
    xs, ys = projectToPixels(np.zeros(4), np.radians([0, 90, 180, 270]), true, size, size)
    for key, x, y in zip(align.DIRECTIONS, xs, ys):
        assert result['directions'][key] == pytest.approx((x/size, y/size), abs=.005)


def test_six_parameter_fit_defaults_to_equisolid_and_partial_fits_are_rejected(monkeypatch):
    from indi_allsky.lens_solver import IndiAllSkyLensSolver
    seed = dict(AZIMUTH_ANGLE=0., LENS_ALTITUDE=90., POINTING_AZIMUTH=0.,
                LATITUDE_OFFSET=0., LONGITUDE_OFFSET=0., IMAGE_CIRCLE_DIAMETER=1500,
                OFFSET_X=0., OFFSET_Y=0., PRECESSION=True)
    request = dict(config={}, size=[2000, 1600], seed=seed, path='frame.jpg', location=[52., 13.],
                   timestamp=1770000000, sensor_shape=None, binning=1)
    fit = dict(success=True, partial=False, values=seed, quality={'stars_matched': 100, 'rms_px': 2.})
    monkeypatch.setattr(IndiAllSkyLensSolver, 'solve', lambda *args, **kw: fit)
    solution_data = align.solve_frame(request)
    assert solution_data['values']['RADIAL_DISTORTION'] == 0.
    assert solution_data['directions']['N'] == pytest.approx([.5, .03125])
    fit['partial'] = True
    assert align.solve_frame(request) is None
    fit['partial'] = False
    fit['quality']['stars_matched'] = 10
    assert align.solve_frame(request) is None


def test_reference_is_earlier_immutable_same_session_exposure(station):
    worker, _, calls, frame = station
    frame()
    path = calls[-1][1]['path']
    assert calls[-1][1]['reference'] is None
    calls[-1][0].finish(None)
    frame(1)
    frame(align.REFERENCE_INTERVAL)
    assert calls[-1][1]['reference'] == path
    frame(1, camera='different')
    assert calls[-1][1]['reference'] is None and worker.solution is None


def test_old_alignment_expires_in_daylight_without_running_solver(station):
    worker, clock, calls, frame = station
    frame()
    calls[-1][0].finish(solution())
    frame(1)
    frame(align.CONFIRM_INTERVAL)
    calls[-1][0].finish(solution())
    assert frame(1)
    # Midday frames continue: the gallery may show the night's orientation
    # for a while, but cannot claim that an unattended move was verified.
    for _ in range(7):
        frame(600, night=False)
    assert worker.solution is None and len(calls) == 2
    assert align.read_alignment_status(worker.config, worker.camera) == 'pending'
