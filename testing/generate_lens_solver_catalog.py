#!/usr/bin/env python3
"""Dev-time catalog extraction script for the lens solver.

VirtualSky ships two star sources:
  * the ~300-star BRIGHT catalog, a literal JS array embedded at
    virtualsky.js:638 (`this.stars = this.convertStarsToRadians([...])`),
    covering roughly mag < 4.5;
  * flask/static/virtualsky/stars.json, a FAINT SUPPLEMENT covering
    mag 4.00-5.49 (zero stars brighter than mag 4.0).

Neither is directly usable at runtime: the embedded array requires parsing
JavaScript out of virtualsky.js (not something the lens_solver package should do on
every request), and it also contains a handful of malformed rows
(`[120412]`, `[55203, 3.8]`) left over from upstream edits.

This script parses both sources, skips malformed rows, merges them,
deduplicates, sorts by magnitude (brightest first), and writes the combined
catalog to indi_allsky/data/lens_solver_stars.json as
`{"stars": [[hip, vmag, ra_deg, dec_deg], ...]}`. The generated file is
committed; indi_allsky.lens_solver.IndiAllSkyLensSolver.loadCatalog() reads
it directly and never parses virtualsky.js at runtime.

Rerun after virtualsky.js or stars.json changes upstream:

    python testing/generate_lens_solver_catalog.py
"""
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
VIRTUALSKY_JS = REPO_ROOT.joinpath(
    'indi_allsky', 'flask', 'static', 'virtualsky', 'virtualsky.js')
STARS_JSON_SUPPLEMENT = REPO_ROOT.joinpath(
    'indi_allsky', 'flask', 'static', 'virtualsky', 'stars.json')
OUTPUT_JSON = REPO_ROOT.joinpath(
    'indi_allsky', 'data', 'lens_solver_stars.json')

# a well-formed row is [hip, vmag, ra_deg, dec_deg]
CATALOG_ROW_LEN = 4
DEDUP_PROXIMITY_DEG = 0.01   # RA/Dec proximity treated as the same star

EMBEDDED_STARS_PATTERN = re.compile(
    r'this\.stars\s*=\s*this\.convertStarsToRadians\((\[.*?\])\);',
    re.DOTALL,
)


def extract_embedded_stars(js_text):
    """Pull the raw (possibly malformed) star literal out of virtualsky.js."""
    match = EMBEDDED_STARS_PATTERN.search(js_text)
    if not match:
        raise ValueError(
            'could not locate "this.stars = this.convertStarsToRadians(...)" '
            'literal in virtualsky.js -- has the upstream source changed?')

    return json.loads(match.group(1))


def load_supplement_stars(stars_json_text):
    """Parse flask/static/virtualsky/stars.json's {"stars": [...]} shape."""
    return json.loads(stars_json_text)['stars']


def filter_well_formed(rows):
    """Drop rows with fewer than CATALOG_ROW_LEN elements.

    Returns (well_formed_rows, skipped_count). well_formed_rows entries are
    normalized to exactly [hip, vmag, ra_deg, dec_deg].
    """
    well_formed = []
    skipped = 0

    for row in rows:
        if len(row) < CATALOG_ROW_LEN:
            skipped += 1
            continue

        well_formed.append([row[0], row[1], row[2], row[3]])

    return well_formed, skipped


def dedup_by_hip(rows):
    """Drop rows whose HIP id already appeared (first occurrence wins)."""
    seen_hips = set()
    deduped = []
    removed = 0

    for row in rows:
        hip = row[0]
        if hip in seen_hips:
            removed += 1
            continue

        seen_hips.add(hip)
        deduped.append(row)

    return deduped, removed


def dedup_by_proximity(rows, proximity_deg=DEDUP_PROXIMITY_DEG):
    """Drop rows within proximity_deg of an already-accepted row in BOTH
    RA and Dec (R3: distinct HIP ids can still be the same physical star
    once two catalogs are merged)."""
    accepted = []
    removed = 0

    for row in rows:
        _, _, ra, dec = row

        is_duplicate = False
        for _, _, accepted_ra, accepted_dec in accepted:
            if (abs(ra - accepted_ra) < proximity_deg
                    and abs(dec - accepted_dec) < proximity_deg):
                is_duplicate = True
                break

        if is_duplicate:
            removed += 1
            continue

        accepted.append(row)

    return accepted, removed


def build_catalog(js_text, stars_json_text):
    """Run the full extract -> filter -> merge -> dedup -> sort pipeline.

    Returns (catalog_rows, stats) where stats is a dict of counts useful
    for the CLI report and for tests.
    """
    embedded_raw = extract_embedded_stars(js_text)
    embedded, embedded_skipped = filter_well_formed(embedded_raw)

    supplement_raw = load_supplement_stars(stars_json_text)
    supplement, supplement_skipped = filter_well_formed(supplement_raw)

    # embedded (bright) catalog first so it wins both dedup passes
    combined = embedded + supplement
    combined, hip_duplicates = dedup_by_hip(combined)
    combined, proximity_duplicates = dedup_by_proximity(combined)

    combined.sort(key=lambda row: row[1])   # brightest (lowest vmag) first

    stats = {
        'embedded_total': len(embedded_raw),
        'embedded_skipped': embedded_skipped,
        'supplement_total': len(supplement_raw),
        'supplement_skipped': supplement_skipped,
        'hip_duplicates_removed': hip_duplicates,
        'proximity_duplicates_removed': proximity_duplicates,
        'catalog_total': len(combined),
        'catalog_mag_le_4_5': sum(1 for row in combined if row[1] <= 4.5),
    }

    return combined, stats


def main():
    js_text = VIRTUALSKY_JS.read_text()
    stars_json_text = STARS_JSON_SUPPLEMENT.read_text()

    catalog, stats = build_catalog(js_text, stars_json_text)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, 'w') as f:
        json.dump({'stars': catalog}, f)

    print('Embedded (virtualsky.js): {0} rows, {1} malformed skipped'.format(
        stats['embedded_total'], stats['embedded_skipped']))
    print('Supplement (stars.json): {0} rows, {1} malformed skipped'.format(
        stats['supplement_total'], stats['supplement_skipped']))
    print('Removed {0} HIP duplicates, {1} proximity duplicates (<{2} deg)'.format(
        stats['hip_duplicates_removed'], stats['proximity_duplicates_removed'],
        DEDUP_PROXIMITY_DEG))
    print('Wrote {0} stars ({1} at mag<=4.5) to {2}'.format(
        stats['catalog_total'], stats['catalog_mag_le_4_5'], OUTPUT_JSON))

    return 0


if __name__ == '__main__':
    sys.exit(main())
