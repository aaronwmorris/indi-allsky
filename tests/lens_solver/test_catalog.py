import json

import numpy
from scipy.spatial import cKDTree

from indi_allsky import lens_solver
from indi_allsky.lens_solver import catalog as catalog_mod
from indi_allsky.lens_solver import IndiAllSkyLensSolver

from tools import generate_lens_solver_catalog as gen_cat


def test_catalog_loads_bright_stars():
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog(mag_limit=4.5)
    assert isinstance(cat, numpy.ndarray)
    assert cat.shape[1] == 3
    assert 200 < cat.shape[0] < 1500
    # sorted brightest (lowest mag) first
    assert numpy.all(numpy.diff(cat[:, 2]) >= 0)
    # Sirius: RA 101.28, Dec -16.71, mag -1.46 (catalog rounds)
    sirius = cat[numpy.argmin(cat[:, 2])]
    assert abs(sirius[0] - 101.3) < 0.5
    assert abs(sirius[1] - (-16.7)) < 0.5


def test_catalog_respects_mag_limit():
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog(mag_limit=2.0)
    # numpy.all on an empty array is vacuously True; assert non-emptiness explicitly.
    assert cat.shape[0] > 0
    assert numpy.all(cat[:, 2] <= 2.0)


def test_catalog_mag_limit_nonempty_and_monotonic():
    solver = IndiAllSkyLensSolver({})
    cat_bright = solver.loadCatalog(mag_limit=2.0)
    cat_full = solver.loadCatalog(mag_limit=4.5)

    assert 10 < cat_bright.shape[0] < cat_full.shape[0]
    # pinned to today's committed data
    assert cat_bright.shape[0] == 53
    assert cat_full.shape[0] == 928


def test_catalog_skips_malformed_rows(tmp_path, monkeypatch):
    # virtualsky.js embeds malformed rows ([120412], [55203, 3.8]); must be dropped, not raised on.
    js_text = gen_cat.VIRTUALSKY_JS.read_text()
    raw = gen_cat.extract_embedded_stars(js_text)
    well_formed, skipped = gen_cat.filter_well_formed(raw)

    assert skipped == 2
    assert len(well_formed) == len(raw) - skipped

    hips = {row[0] for row in well_formed}
    assert 120412 not in hips
    assert 55203 not in hips

    # also guard loadCatalog itself in case a regenerated data file has one
    bad_catalog = tmp_path / 'lens_solver_stars.json'
    bad_catalog.write_text(json.dumps({'stars': [
        [120412],
        [55203, 3.8],
        [32349, -1.46, 101.287, -16.72],
    ]}))
    monkeypatch.setattr(catalog_mod, 'CATALOG_JSON', bad_catalog)

    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog(mag_limit=10.0)
    assert cat.shape == (1, 3)
    assert abs(cat[0, 2] - (-1.46)) < 1e-9


def test_catalog_has_no_duplicate_stars():
    with open(catalog_mod.CATALOG_JSON) as f:
        data = json.load(f)
    stars = data['stars']

    hips = [row[0] for row in stars]
    assert len(hips) == len(set(hips))

    coords = numpy.array([[row[2], row[3]] for row in stars])
    tree = cKDTree(coords)
    close_pairs = tree.query_pairs(r=0.01, p=numpy.inf)
    assert len(close_pairs) == 0


def test_catalog_ranges_sane():
    # whole-catalog check: Sirius alone can't catch a column-order bug
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog(mag_limit=10.0)

    assert numpy.all(cat[:, 0] >= 0.0)
    assert numpy.all(cat[:, 0] < 360.0)
    assert numpy.all(cat[:, 1] >= -90.0)
    assert numpy.all(cat[:, 1] <= 90.0)
    assert not numpy.any(numpy.isnan(cat))


def test_catalog_contains_sirius_guard():
    # Non-deletable guard: Sirius (mag -1.46) must be present.
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog(mag_limit=lens_solver.CATALOG_MAG_LIMIT)
    assert cat[:, 2].min() < 0.0


def test_loadcatalog_empty_result_shape():
    # must be shape (0, 3), not (0,), when nothing matches
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog(mag_limit=-5.0)
    assert cat.shape == (0, 3)
