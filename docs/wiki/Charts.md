# Charts

Open **Charts > Manage charts** to jump to the settings below the chart grid.
Add, remove, or reorder custom charts, then select **Save Configuration** at the
top of the settings. Changing saved-image selections automatically checks
**Reload on Save** so the capture worker applies them. Uncheck it to defer
capture-side changes until the next service reload. After disabling saved-image
charts, the existing latest image retains its baked charts until a new frame is
captured; existing files are not rewritten.
**History** selects charts on the Charts page. **Browser** independently selects
live charts over the latest-image view; **Saved image** writes charts into new
capture images. Select either destination or both, including different charts for
each. Existing nine-slot configurations load automatically, and both image
destinations default to off. Up to 64 custom charts are
supported as a safety bound.

## Axes

The existing time-history choices, time labels, line/point behavior, and detection
bars are retained. Existing custom-chart minima remain suggested lower bounds,
not hard cutoffs. Missing readings appear as gaps rather than fabricated zeroes.

Each standard or custom chart has a sliders icon in the chart settings.
Its **Y-axis limits** control accepts an optional minimum and maximum. Blank
values retain existing automatic/suggested scaling. Explicit values set a fixed
bound; if both are entered, the minimum must be below the maximum. Clearing both
restores the default behavior. Limits apply to history, browser and saved-image
charts, and remain attached to the chart when it is renamed or reordered.
Histogram scaling is unchanged.

## Image Overlays

History, top offset, width, and opacity are shared by both image destinations.
Browser charts avoid the status message, scroll within the image area and are
included in fullscreen. They appear on the right when saved-image charts are
also configured. Browser-only charts do not modify image files.

Browser charts start below the recorded image-label bounds and status message.
Drag any chart header with a mouse or touch to move the browser chart group;
its position is remembered per camera in this browser. Double-click a header to
restore automatic placement. Focus a header and use arrow keys to move it,
or Shift plus arrow keys for fine adjustment. Placement follows image scaling,
window resizing, and fullscreen. Older images without label-bound metadata use
the configured top offset until a new capture supplies the bounds.

One selected saved-image chart uses 1.5 times the configured width and a height
of 224 px (390 x 224 px at the default width). Multiple saved-image charts retain
the configured width and compact 112 px height. Width is limited to the image's
available space. Browser charts show numeric and first/last time axes with the
same line styling and scaling as saved-image charts.

Saved-image charts are rendered with Matplotlib's headless Agg backend after
image labels and before compression. They sit below upper-left labels and flow
into additional columns as needed, without resizing the image. Charts that cannot
fit are skipped with a capture-log warning. They include camera-specific history
and the current frame, and are disabled in focus mode. New latest images, saved
images, thumbnails, uploads and timelapses built from those images contain the
charts. Existing files, raw/FITS images, keograms, panoramas and circular-display
outputs are not changed, and measurements occur before chart compositing.

Existing capture installations must install `matplotlib>=3.5.3` in their capture
virtual environment, or rerun the normal dependency setup. A missing renderer is
logged without stopping capture. Web-only installations do not need Matplotlib.

## Future Sources

[The shared model](../../indi_allsky/charts.py) defines stable chart IDs, numeric
sources, labels, and validation. Future windspeed or MLX cloudiness features can
publish readings in existing `sensor_user_N` or `sensor_temp_N` image metadata
slots without changing either renderer. Dedicated named sources need an entry in
`METADATA_SOURCES` and the configuration form's `CUSTOM_CHART_choices`.
This implementation does not depend on those pending sensor PRs.

Capture publishes dynamic definitions for synced cameras. Local cameras use
current settings; remote selections match IDs, falling back to source keys.
`AXIS_LIMITS` stores optional bounds by chart ID. `OVERLAY_IDS` retains its existing
browser-only meaning; `SAVED_IMAGE_IDS` stores the independent capture selections.

## Validation

Run `python -m pytest tests/test_charts.py`. Tests cover the shared model and
isolated production handler, validator, persistence, reload queue, metadata and
template paths, plus real SQLite history and decoded raster output.
The preview at `http://127.0.0.1:5068/charts` uses production scripts/templates and
the raster compositor with sample data and memory-only settings. It is not a full
Linux Flask/camera integration test.