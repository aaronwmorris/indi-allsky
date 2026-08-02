# ASI676MC purple-frame handling and calibration

## Purpose and safety boundary

Some ZWO ASI676MC cameras occasionally deliver a RAW16 RGGB mosaic with a
strong purple cast. This feature detects that specific failure, can exclude the
affected frame without modifying it, and can optionally repair it before the
normal indi-allsky image pipeline continues.

Leave **Enable ASI676MC Purple-frame Handling** off unless the camera actually
produces this failure. The implementation is deliberately narrow:

- the master option must be enabled;
- the camera name must identify an ASI676MC;
- the input must be a two-dimensional, even-sized RAW16 mosaic;
- the Bayer pattern must be RGGB;
- binning must be 1x1; and
- `XBAYROFF` and `YBAYROFF` must both be zero.

Unsupported input is not changed. A reason is recorded in the image metadata
and written to the log.

New configurations default to **Exclude Only**. This mode detects and flags a
purple frame, preserves its original pixels, and excludes it from timelapses.
Pixel repair begins only after an operator explicitly disables Exclude Only.

## Runtime processing

Purple-frame handling runs immediately after indi-allsky opens the camera FITS
and before dark-frame calibration, debayering, stacking, or ordinary FITS
saving. This order is important because the detector and repair operate on the
original RGGB parity layout.

The image worker follows this sequence:

1. Confirm that the feature, camera, and RAW layout are eligible.
2. Sample the four RGGB parities and calculate the purple, red-side, and
   blue-side ratios.
3. Classify the frame as normal or purple using the configured thresholds.
4. In Exclude Only mode, retain a purple frame unchanged and mark it excluded.
5. In repair mode, repair a temporary copy of a purple frame.
6. Recalculate the signature on the temporary copy.
7. Commit the copy only if it no longer matches the failure signature.

That last step is atomic from the rest of the image pipeline's perspective. If
post-repair validation fails, the original mosaic is retained and the image is
marked `validation_failed`.

The status stored under `asi676mc_repair_status` is one of:

| Status | Meaning |
| --- | --- |
| `normal` | The frame did not match the purple-frame signature. |
| `excluded` | A purple frame was detected in Exclude Only mode; pixels were retained and the frame was excluded from timelapses. |
| `repaired` | A purple frame was repaired and passed post-repair validation. |
| `validation_failed` | Repair output still matched the failure; the original frame was retained. |
| `skipped` | The camera or RAW layout did not meet the safety boundary, or the configuration was invalid. |

The metadata also retains the available before/after ratios, timing, and reason
text. Gallery decoration is optional and does not affect processing.

## Detection and repair model

The detector sparsely samples the four Bayer parities while preserving RGGB
alignment. It uses three ratios so a naturally magenta scene is less likely to
be mistaken for the camera failure:

- `PURPLE_RATIO_THRESHOLD` measures the combined red/blue dominance over the
  two green parities;
- `RED_SIDE_RATIO_THRESHOLD` requires the red parity to dominate green; and
- `BLUE_SIDE_RATIO_THRESHOLD` requires the blue parity to dominate green.

All three conditions must be met.

The faulty stream is repaired in bounded row chunks to limit peak memory use.
The repair:

1. removes the observed one-row phase error;
2. applies a calibrated lookup table to each RGGB parity;
3. records prematurely clipped green locations before gain correction;
4. reconstructs those green highlights from the repaired red/blue context;
5. blends strongly coloured and near-neutral highlight estimates across the
   configured highlight boundaries; and
6. copies a stable neighbouring row into the final row, whose source is lost by
   the phase correction.

The runtime and calibration engine use the same detector, repair function,
highlight boundary conversion, and defaults. There is no second copy of the
image-correction algorithm to drift out of sync.

## Configuration reference

All keys live below `IMAGE_ASI676MC_REPAIR`.

| Key | Default | Purpose |
| --- | ---: | --- |
| `ENABLE` | `False` | Master safety switch. Leave off for unaffected cameras. |
| `EXCLUDE_ONLY` | `True` | Detect, flag, and exclude purple frames without changing pixels. Disable only after reviewing calibration. |
| `LOG_EVERY_FRAME` | `False` | Log normal-frame checks at info level instead of debug level. Purple frames and failures are always logged prominently. |
| `GALLERY_ENABLE` | `True` | Show repair/exclusion status in the gallery and enable the repaired-frame filter. |
| `SAVE_DIAGNOSTIC_FITS` | `False` | Save the untouched purple frame and its following frame as low-disk calibration evidence. |
| `SAVE_PRECEDING_FITS` | `False` | Also cache the immediately preceding normal FITS and save it when the next compatible frame is purple. Requires the parent diagnostic option. |
| `PURPLE_RATIO_THRESHOLD` | `1.5` | Combined purple signature threshold. |
| `RED_SIDE_RATIO_THRESHOLD` | `1.25` | Red-side signature threshold. |
| `BLUE_SIDE_RATIO_THRESHOLD` | `1.5` | Blue-side signature threshold. |
| `SAMPLE_STEP` | `32` | Even Bayer-preserving interval used by live detection. |
| `SOURCE_SATURATION_THRESHOLD` | `65000` | Faulty-stream level treated as clipped for green reconstruction. |
| `GAIN_R` | `0.91004` | Repair gain for the red parity. |
| `GAIN_G1` | `1.68652` | Repair gain for the first green parity. |
| `GAIN_G2` | `1.09238` | Repair gain for the second green parity. |
| `GAIN_B` | `0.59537` | Repair gain for the blue parity. |
| `HIGHLIGHT_BLEND_START_RATIO` | `0.55` | Red/blue balance at which highlight blending begins. |
| `HIGHLIGHT_BLEND_END_RATIO` | `0.75` | Red/blue balance at which the near-neutral estimate takes over. |
| `CHUNK_ROWS` | `128` | Even number of rows processed at a time during repair. |

The web calibration tool derives only the four parity gains, saturation
threshold, and two highlight blend ratios. Detection thresholds, sample step,
chunk size, and operational switches remain deliberate operator settings.

## Collecting calibration evidence

Calibration needs the untouched purple mosaic and at least one compatible
normal reference. A normal/purple/normal triplet is preferable because the two
normal frames can be averaged, but a normal/purple pair is valid.

There are two supported collection strategies.

### Low-disk diagnostic capture

Enable **Save Bad and Following RAW FITS**. For each detected purple frame,
indi-allsky copies the original camera FITS before the temporary repaired array
can affect later processing, then saves the immediately following ingested
frame. This mode adds no persistent full-frame memory cache.

Optionally enable **Also Save Preceding RAW FITS**. The image worker then keeps
one untouched, normal FITS byte string per active camera in memory. It writes
that cached frame only if the next compatible frame is purple. The cache is
advanced after each normal frame and discarded after a purple, skipped, or
incompatible frame. The option improves evidence quality at the cost of about
one full FITS of memory per active camera and one additional saved FITS per
purple event.

Each diagnostic FITS is a normal database-managed FITS asset with role metadata:

- `preceding` - normal frame immediately before the purple frame;
- `bad` - untouched purple frame; or
- `following` - frame immediately after the purple frame.

One physical FITS can carry more than one role when consecutive groups share a
frame. Diagnostic files use the normal FITS upload destinations, retention
setting, and expiration task. They can be downloaded from the standard Image
Viewer when the relevant download controls are available.

### Ordinary FITS capture

In **Exclude Only** mode, ordinary FITS still contain the original mosaic. Set
ordinary FITS saving to **Every Image** temporarily to collect complete
normal/purple/normal sequences.

When repair is active, ordinary FITS are written from the already repaired
image and may no longer contain the original failure. Use the diagnostic FITS
option if untouched purple evidence is required.

The settings and calibration pages display a combined capture outlook based on
the current repair and FITS options. That message describes future captures;
the discovery process judges existing files by their actual metadata and
availability.

## Calibration tool

The authenticated tool appears in the Tools menu only while purple-frame
handling is enabled. A real signed-in session is required even on installations
where the general login requirement is relaxed. Applying values additionally
requires an administrator account.

The page supports two input paths.

### Manual multi-file upload

The file picker accepts all selected FITS at once. The browser uploads them
sequentially so a Raspberry Pi does not need to buffer a large collection in
one request. Limits are enforced on both browser and server:

- 200 files per session;
- 256 MiB per file; and
- 2 GiB total per session.

Select at least 14 files so the collection can contain seven purple frames and
seven distinct normal references. Unmatched extra files are ignored only when
the submitted collection still meets the strict evidence rules.

The page requires modern JavaScript features used for multi-file selection,
streamed requests, cancellation, progress, polling, and result restoration. It
checks these capabilities on load and displays a blocking explanation if the
browser cannot provide them.

The **Cancel upload** action aborts the current request and asks the server to
discard the session. A server-side marker also prevents a late request from
reviving a cancelled session.

### Discover saved FITS

Automatic discovery searches database-managed FITS for the selected ASI676MC.
It starts with the newest flagged purple frame and works backwards within the
configured FITS retention period. The requested limit is 7 to 100 purple-frame
groups. Discovery stops when it reaches that limit or runs out of usable
evidence; it proceeds with fewer than requested when at least seven complete
groups remain.

Explicit diagnostic role metadata is preferred. Ordinary FITS can also be
matched by capture time and compatibility. A candidate reference must agree on
camera, dimensions, exposure, gain, binning, and Bayer pattern. The preceding
and following files are selected dynamically, so pairs and triplets can be
mixed in one run.

Database files are staged with filesystem links where possible. This consumes
no second copy of the FITS data. A hard link keeps the selected content stable
if regular expiry reaches the original database row while calibration is
running; a symbolic link is the cross-filesystem fallback. Removing a staging
link never removes the database FITS it points to.

## Evidence validation and fitting

Before fitting, the engine opens FITS through the Astropy support already used
by indi-allsky and rejects unreadable, non-RAW16, non-RGGB, odd-sized, or
clearly different-camera input. It classifies every usable frame with the
same signature implementation used by live processing.

A successful collection requires:

- at least seven purple frames;
- at least seven distinct compatible normal references;
- at least one normal reference for every used purple frame;
- at least two exposure levels;
- clean separation between normal and purple signature ranges;
- sufficient unsaturated samples for each Bayer parity; and
- sufficient clipped-highlight evidence to fit both blend boundaries.

Normal references that change too much across a two-sided triplet are rejected
at the affected sample locations. This prevents moving cloud, aircraft, or
other transient content from being fitted as a camera correction. Robust
medians and median-absolute-deviation filtering reduce the influence of the
remaining outliers.

The engine then estimates the four parity gains, finds the premature clipping
plateau, searches the supported highlight-boundary grid, and validates the
rounded values by running every matched purple frame through the live repair
path. Calibration fails if any repaired frame still matches the failure
signature.

## Results, report, and applying values

A successful results page shows:

- the derived value beside the current configured value;
- matched purple and normal counts;
- pair/triplet coverage, exposure coverage, and signature ranges;
- rejected or unused evidence and plain-language warnings; and
- whether the result effectively matches the current configuration within a
  deliberately small tolerance.

The downloadable text report is generated for the integrated workflow. It
records the evidence source, quality assessment, values, comparison with the
configuration at the start of calibration, warnings, cleanup outcome, and
recommended next actions. It never exposes private staging paths.

An administrator can select **Apply values and reload**. The server writes only
the seven derived keys, using the same configuration-save mechanism as the
settings page, then queues an application reload. It refuses the update if the
configuration changed after calibration began; this prevents an older result
from overwriting a newer settings edit. Operational switches such as Enable and
Exclude Only are never changed by calibration.

Results are retained in the browser by an unguessable session ID so a user can
visit another page and return. The browser stores no FITS data or calibration
values. Every result, report, discard, and apply request rechecks session
ownership. **Reset / recalibrate** discards the retained result and returns the
page to the input view.

## Session storage and cleanup

Calibration sessions live below the non-public Flask instance directory, or
below `ASI676MC_CALIBRATION_FOLDER` when explicitly configured. Manifest and
result files are written atomically because web workers and the video worker
may read them concurrently.

The CPU-heavy fit and full-resolution validation run as a low-priority video
queue task rather than inside a web request. This avoids request timeouts and
keeps capture and web workers responsive.

Input cleanup is source-aware:

- browser-uploaded FITS are deleted immediately after the run succeeds or
  fails;
- database staging links are deleted immediately, while their database source
  FITS remain untouched; and
- cancellation and reset remove the session directly.

If immediate cleanup is interrupted by a crash, power loss, or unavailable
filesystem, the regular expiration task removes calibration sessions older
than seven days. This fixed session retention is independent of database FITS
retention. Database FITS and diagnostic role links continue to use the normal
indi-allsky FITS expiration behavior.

## Operator workflow

1. Confirm that the ASI676MC actually produces the purple-frame failure.
2. Enable purple-frame handling and leave Exclude Only enabled.
3. Choose either low-disk diagnostic FITS or temporary ordinary FITS saving for
   every image. Enable preceding-frame caching only when the additional memory
   and disk use are acceptable.
4. Collect several purple events across at least two exposure levels.
5. Open **Tools -> ASI676MC Calibration** while signed in.
6. Discover saved FITS or select a multi-file upload.
7. Review the evidence summary, warnings, derived values, and current values.
8. Download the report if an audit copy is useful.
9. As an administrator, apply the result only after it looks credible.
10. Disable Exclude Only to activate repair, then monitor gallery status and
    logs for validation failures.
11. Return FITS-saving options to the desired long-term disk-use policy.

## Troubleshooting

**The tool is absent from the menu**

Enable ASI676MC purple-frame handling in Image settings and sign in.

**No saved FITS groups are found**

The current settings describe future evidence only. Existing purple frames may
have expired or may never have been saved as untouched FITS. Enable either
diagnostic FITS or Exclude Only plus ordinary FITS for every image, collect new
events, and try again.

**Files upload but calibration rejects the collection**

Check that the collection contains uncompressed ASI676MC RAW16 RGGB files,
seven purple frames, a compatible adjacent normal frame for each, two exposure
levels, and visible clipped highlights. Extra unmatched files do not compensate
for a missing minimum.

**Calibration succeeds but applying values is refused**

The indi-allsky configuration changed after the run began, or the signed-in
account is not an administrator. Start a new calibration against the current
configuration.

**Repair validation fails during capture**

The original frame is preserved. Collect its untouched diagnostic group and
recalibrate; do not loosen detection thresholds merely to suppress the warning.

## Maintainer map

| File | Responsibility |
| --- | --- |
| `indi_allsky/config.py` | Conservative new-install defaults, including disabled handling and Exclude Only mode. |
| `indi_allsky/asi676mc.py` | Authoritative settings normalization, signature detection, repair, validation, metadata, and diagnostic-role helpers. |
| `indi_allsky/processing.py` | Runtime eligibility checks, Exclude Only behavior, repair invocation, and logging. |
| `indi_allsky/image.py` | Untouched diagnostic FITS capture, optional preceding-frame cache, database records, and rendered-image metadata. |
| `indi_allsky/asi676mc_calibration_engine.py` | FITS inspection, matching, evidence policy, numerical fitting, and validation through the live repair path. |
| `indi_allsky/asi676mc_calibration.py` | Private sessions, uploads, database discovery/staging, cleanup, user guidance, result comparison, and text reports. |
| `indi_allsky/video.py` | Background calibration task and seven-day session cleanup fallback. |
| `indi_allsky/flask/forms.py` | Settings validators, calibration controls, saved-FITS lookup, viewer assets, and gallery filtering. |
| `indi_allsky/flask/views.py` | Authenticated endpoints, task queueing, result/report access, and configuration apply/reload. |
| `indi_allsky/flask/base_views.py` and `templates/base.html` | Context-aware Tools-menu visibility. |
| `indi_allsky/flask/templates/config.html` | Settings UI and contextual guidance. |
| `indi_allsky/flask/templates/asi676mc_calibration.html` | Calibration input, progress, cancellation, results, report, reset, and browser capability checks. |
| `indi_allsky/flask/templates/gallery.html` | Optional repair/exclusion badges, outlines, and repaired-frame filtering. |
| `indi_allsky/flask/templates/imageviewer.html` | Diagnostic preceding/purple/following FITS downloads. |
| `testing/image/test_asi676mc_repair.py` | Detection, repair, validation, metadata, and diagnostic helper coverage. |
| `testing/image/test_asi676mc_calibration_engine.py` | FITS inspection, matching, fitting, evidence policy, and shared-runtime coverage. |
| `testing/image/test_asi676mc_web_calibration.py` | Sessions, cleanup, discovery, guidance, reports, and web workflow coverage. |

Run the focused tests from the repository root:

```text
python -m unittest \
    testing.image.test_asi676mc_repair \
    testing.image.test_asi676mc_calibration_engine \
    testing.image.test_asi676mc_web_calibration
```

When changing the correction math, update the authoritative implementation in
`indi_allsky/asi676mc.py` first. The calibration engine must continue to call
that implementation for classification and final validation. When changing a
setting or role, trace it through defaults, form validation, view persistence,
help text, metadata, report output, and tests so the complete feature remains
coherent.
