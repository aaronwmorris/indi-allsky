import functools
import json
from pathlib import Path

import numpy


# do not raise: denser catalogs cause confident-wrong fits (diameter off
# 74px at 5.5); 4.5 validated across a latitude/epoch/seed grid
CATALOG_MAG_LIMIT = 4.5
# fitParameters accepts arbitrary catalogs, so validatedness is enforced
# there, not just defaulted here; ceiling set with headroom over 4.5's rows
CATALOG_VALIDATED_ROW_CEILING = 1000
CATALOG_VALIDATION_EPSILON_MAG = 0.05

# catalog rows are [hip, vmag, ra_deg, dec_deg], extracted from the vendored
# virtualsky.js + stars.json by tools/generate_lens_solver_catalog.py
CATALOG_ROW_LEN = 4
CATALOG_JSON = Path(__file__).parent.parent.joinpath(
    'data', 'lens_solver_stars.json')


def loadCatalog(mag_limit=CATALOG_MAG_LIMIT):
    # copy so a caller mutating the array cannot poison the cache;
    # CATALOG_JSON is read at call time so tests may substitute it
    return _loadCatalogArray(str(CATALOG_JSON), float(mag_limit)).copy()


@functools.lru_cache(maxsize=4)
def _loadCatalogArray(catalog_json, mag_limit):
    # cached: the committed catalog is identical on every solve request
    with open(catalog_json) as f:
        data = json.load(f)

    rows = []
    for row in data['stars']:
        # skip malformed rows a future catalog regeneration might reintroduce
        if len(row) < CATALOG_ROW_LEN:
            continue

        _hip, vmag, ra_deg, dec_deg = row[0], row[1], row[2], row[3]
        if vmag > mag_limit:
            continue

        rows.append([ra_deg, dec_deg, vmag])

    if not rows:
        return numpy.zeros((0, 3), dtype=numpy.float64)

    stars = numpy.array(rows, dtype=numpy.float64)
    return stars[numpy.argsort(stars[:, 2])]
