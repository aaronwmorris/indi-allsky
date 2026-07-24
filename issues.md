## issues.md — round 1

| id | category | state | description | file:line |
|----|----------|-------|-------------|-----------|
| 1  | COVERAGE_GAP | OPEN | No tests for ESP32ImageView (size validation, auth bypass, image conversion paths) | indi_allsky/flask/views.py:11950 |
| 2  | COVERAGE_GAP | OPEN | FITS swapaxes will raise AxisError if FITS data is 2D (monochrome camera); mirrors pre-existing pattern at line 7215 | indi_allsky/flask/views.py:12037 |
| 3  | COVERAGE_GAP | OPEN | hdulist from fits.open() is never closed (resource leak); mirrors pre-existing pattern at line 7209 | indi_allsky/flask/views.py:12033 |
| 4  | CODE_DEFECT | CHECKED-FIXED | camera_id int() conversion now wrapped in try/except (ValueError, TypeError) at lines 11960-11963 | indi_allsky/flask/views.py:11960 |
