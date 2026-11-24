# Night Report

Each completed local night keogram gets a Night Report. The PNG shows the
keogram alongside the selected sensor readings. The CSV contains all available
measurements for the same observations. Open **Night Report** on the night archive card or keogram page.
An administrator can select the plotted measurements and choose **Save and
regenerate**. The selection is remembered per camera for future reports.

The report uses actual capture timestamps. Changing exposure intervals and
missing images do not compress the timeline. Missing or invalid sensor values
break curves; a measured zero remains zero. Air temperature and dew point share
a plot when both are selected. Dew point is calculated from valid temperature
and humidity readings from the same sensor, rather than a potentially stale
derived slot. Lux is illuminance, not calibrated SQM.

Astronomical twilight boundaries (-12 and -18 degrees solar center) and lunar
rise/set are marked when they fall within the recording. Event calculations use
the location recorded with exposures where available. Old nights without a
recorded location explicitly identify the current camera location as a fallback.
Moonrise/set assume an unobstructed standard horizon, not a local tree line.

The video worker checks for missing reports while its queue is idle. It retries
failed reports with increasing delays. A completed keogram stays available
even if report generation fails. A compact source cache retains measurements and keogram
strips, allowing a different plot selection after full exposures expire. Report
files and their cache are deleted with their keogram. Existing remote/S3-only
assets are not rendered remotely or exported automatically by this feature.

## Display the latest report in Home Assistant

Use `/indi-allsky/latestnightreport?camera_id=1` as the image URL for camera 1.
It redirects to the PNG for the most recent observing night with a completed
report. Add `&format=csv` to download its measurements. While a newer night is
waiting for its first report, the URL still returns the previous night. If the
camera has no report available to the caller, the request returns HTTP 404.
The same media access settings apply as when opening the report from the archive.

A client can connect to `/indi-allsky/ws/events` and fetch the latest report
when the connection opens. On each `night_report_complete` event for its
`data.camera_id`, it can fetch that URL again. The worker sends the event after
publishing both files, including when it regenerates an older report.
`data.dayDate` identifies the observing night and `data.created_at` gives the
UTC publication time. To open the specific report that triggered the event,
use `/indi-allsky/night_report?keogram_id=<data.keogram_id>&format=png`.
After a disconnect, fetch the latest report again because the stream does not
replay missed events.

## CSV interchange format, version 1

UTF-8, comma-separated, a header row, decimal points, no locale-dependent dates.
Each row represents an included nighttime Allsky exposure with an unambiguous timestamp. PNG selection does not discard
other available measurements from CSV. Read columns by name so imports continue
to work when later versions add measurements.

| Column | Meaning |
| --- | --- |
| `schema_version` | `1` for this contract |
| `camera_uuid`, `camera_id`, `image_id` | Stable station UUID and local database identifiers; UUID plus image ID identifies an observation |
| `night_date` | Observing-night date, including recordings after midnight |
| `timestamp_utc`, `unix_time` | The same observation time as ISO 8601 UTC and epoch seconds |
| `timestamp_local`, `utc_offset_seconds` | Historical local time with explicit offset; repeated DST hours remain distinct |
| `exposure_seconds` | Recorded exposure duration, blank if unknown |
| `time_reference` | `recorded_capture_time`; **not** a promise of shutter-open time |
| `sensor_validity` | `tracked` when validity metadata was recorded, otherwise `legacy_unverified` |
| `gap_before_seconds` | Elapsed time since the preceding observation; blank for the first row. This includes the ordinary capture cadence, not just downtime |
| `valid_fields` | Semicolon-separated IDs of metrics with a usable value in this row |
| `metric_catalog_json` | The first row includes a JSON catalogue of metric IDs, labels, units, kinds and corresponding CSV column names; later rows leave this cell empty |
| Measurement columns | Explicit units in names, e.g. `sky_temperature_c`, `sky_brightness_lux`, `air_temperature_c`, `dew_point_c`, or additional `sensor_user_N_<unit>` columns |

Empty cells mean missing/invalid/unknown, never zero. Stock captures have no per-sensor validity flag. The export labels
those rows `legacy_unverified` and preserves the values as recorded.
An omitted measurement column means no available measurements of that kind in the report. Do not fill
gaps indefinitely. Source measurements are those carried with the exposure;
they are not separate, precisely synchronized sensor acquisition timestamps.
The libcamera and INDI drivers assign the capture timestamp after exposure when
the image is received. Do not treat that time as a precise exposure start or
subtract exposure duration to invent an exact start.

For comparison with light frames, use the observation time and exposure from
the FITS header, convert to UTC, and check the coverage of Allsky samples over
that interval. Leave frames with insufficient telemetry unclassified.
