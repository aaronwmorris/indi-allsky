# Charts

Open **Charts > Manage charts** to jump to the settings below the chart grid.
Add, remove, or reorder custom charts, then select **Save charts**.
**History** selects charts on the Charts page; **On image** independently selects
compact charts on the latest-image view. Existing nine-slot configurations load
automatically, and image overlays default to off. Up to 64 custom charts are
supported as a safety bound.

## Axes

The existing time-history choices, time labels, line/point behavior, and detection
bars are retained. Existing custom-chart minima remain suggested lower bounds,
not hard cutoffs. Missing readings appear as gaps rather than fabricated zeroes.

Each standard or custom chart has a sliders icon in the chart settings.
Its **Y-axis limits** control accepts an optional minimum and maximum. Blank
values retain existing automatic/suggested scaling. Explicit values set a fixed
bound; if both are entered, the minimum must be below the maximum. Clearing both
restores the default behavior. Limits apply to the history chart and its image
overlay, and remain attached to the chart when it is renamed or reordered.
Histogram scaling is unchanged.

## Image Overlays

Overlay history, top offset, width, and opacity are configurable. The top offset
positions charts below text baked into the image; charts also avoid the browser's
status message. Multiple charts scroll within the image area. Fullscreen includes
the overlays. Captured images and timelapses are not modified.

## Future Sources

[The shared model](../../indi_allsky/charts.py) defines stable chart IDs, numeric
sources, labels, and validation. Future windspeed or MLX cloudiness features can
publish readings in existing `sensor_user_N` or `sensor_temp_N` image metadata
slots without changing either renderer. Dedicated named sources need an entry in
`METADATA_SOURCES` and the configuration form's `CUSTOM_CHART_choices`.
This implementation does not depend on those pending sensor PRs.

Capture publishes dynamic definitions for synced cameras. Local cameras use
current settings; remote selections match IDs, falling back to source keys.
`AXIS_LIMITS` stores optional viewer-side bounds by chart ID.

## Validation

Run `python -m pytest tests/test_charts.py`. Tests cover the shared model and
isolated production handler, validator, persistence, metadata, and template paths.
The preview at `http://127.0.0.1:5067/settings` uses production scripts/templates
with sample data and memory-only settings. It is not a full Linux Flask/camera
integration test.