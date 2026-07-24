## gitissuesol-state.md — after round 1

**Task:** Fix for GitHub issue #2693: Feature - Support for esp32 round disc allsky viewers
**Round:** 1 of 3
**Timestamp:** 2026-07-24T21:52:22.153Z

**Evaluation summary:**
**Concerns:**

[1] COVERAGE_GAP OPEN `indi_allsky/flask/views.py:11950` — No automated tests for ESP32ImageView covering size validation, auth bypass, and image format conversion paths.

[2] COVERAGE_GAP OPEN `indi_allsky/flask/views.py:12037` — `numpy.swapaxes(..., 0, 2)` raises AxisError on 2D monochrome FITS data; mirrors pre-existing pattern at line 7215, not a new regression.

[3] COVERAGE_GAP OPEN `indi_allsky/flask/views.py:12033` — `fits.open()` result `hdulist` is never closed; mirrors pre-existing pattern at line 7209.

[4] CODE_DEFECT CHECKED-FIXED `indi_allsky/flask/views.py:11960` — camera_id int conversion is correctly wrapped in try/except.

STATUS: DONE