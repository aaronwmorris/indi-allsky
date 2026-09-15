# ASI676MC purple-frame handling and calibration

## Overview

Some ZWO ASI676MC cameras occasionally deliver a RAW16 RGGB mosaic with a
strong purple cast. This feature can detect that specific failure, exclude the
affected frame without changing its pixels, or repair it before the normal
indi-allsky image pipeline continues.

Leave **Enable ASI676MC purple-frame handling** off unless the camera actually
produces this failure. New configurations start in **Detect and exclude only**
mode so purple frames are preserved while calibration evidence is collected.
Repair begins only after that option is deliberately turned off.

### Safety boundary

Handling is limited to captures that meet every one of these conditions:

- the master option is enabled;
- the camera name identifies an ASI676MC;
- the input is a two-dimensional, even-sized RAW16 mosaic;
- the Bayer pattern is RGGB;
- binning is 1x1; and
- `XBAYROFF` and `YBAYROFF` are both zero.

An unsupported ASI676MC RAW layout is not changed. The reason is recorded in
image metadata and written to the log. Other camera models stay outside this
feature and are mentioned only at debug log level; they do not receive
ASI676MC repair metadata.

### Recommended workflow

1. In Image Settings, turn on **Enable ASI676MC purple-frame handling** and
   leave **Detect and exclude only** enabled.
2. Enable **Save purple and following normal FITS for calibration**. Leave
   standard FITS saving off unless diagnostic saving fails to catch the purple
   frame or the standard files are needed for another purpose.
3. Collect at least seven purple events across at least two exposure settings.
   **Also save the preceding normal FITS** can improve the evidence, but costs
   about one FITS frame of memory and up to one additional saved FITS per event.
4. Open **Tools > Fix ASI676MC purple frames** and choose **Use saved FITS**.
   **Upload a FITS collection** is available when the evidence was collected
   elsewhere.
5. Follow the outcome shown by the tool:
   - for a full calibration, review and save the calibration values;
   - for a detection-threshold suggestion, confirm the likely purple frames,
     save only the recommended detection settings, start over, and rerun; or
   - for a failed analysis, follow the retained explanation and collect more
     suitable evidence.
6. After a credible full calibration, turn off **Detect and exclude only** to
   begin repair. Monitor the gallery and logs for validation failures, then
   return FITS-saving options to the desired long-term disk-use policy.

## Runtime behavior

ASI676MC handling runs immediately after indi-allsky opens the camera FITS and
before dark-frame calibration, debayering, stacking, or standard FITS saving.
The detector and repair therefore operate on the original RGGB parity layout.

The image worker follows this sequence:

1. Confirm that the feature, camera, and RAW layout are eligible.
2. Sample the four RGGB parities and calculate the overall purple, red-side,
   and blue-side ratios.
3. Classify the frame using all three configured thresholds.
4. In **Detect and exclude only** mode, keep a purple frame unchanged and mark
   it excluded.
5. In repair mode, repair a temporary copy of a purple frame.
6. Recalculate the signature on the temporary copy.
7. Commit the copy only if it no longer matches the failure signature.

The last step is atomic from the rest of the image pipeline's perspective. If
validation fails, the original mosaic is retained and the image is marked
`validation_failed`.

### Status, outputs, and notifications

The status stored under `asi676mc_repair_status` is one of:

| Status | Meaning |
| --- | --- |
| `normal` | The frame did not match the purple-frame signature. |
| `excluded` | A purple frame was detected in **Detect and exclude only** mode; its pixels were retained and it was excluded from standard timelapses. |
| `repaired` | A purple frame was repaired and passed post-repair validation. |
| `validation_failed` | The repair still matched the failure; the original frame was retained and excluded from standard timelapses. |
| `skipped` | The camera or RAW layout did not meet the safety boundary, or the configuration was invalid. |

Frames with `excluded` or `validation_failed` status are also omitted from
stacking history and automatic exposure control, so they cannot affect the next
normal image.

Metadata also retains the available before/after ratios, timing, and reason
text. Gallery decoration is optional and does not affect processing.

A skipped check or failed post-repair validation creates a Camera
notification. The first occurrence appears immediately; identical notification
types are suppressed for two hours. Normal frames, expected exclusion-only
detections, and successful repairs remain visible through their logs and
gallery metadata without generating notifications.

### Detection and repair model

The detector sparsely samples the four Bayer parities while preserving RGGB
alignment. A naturally magenta scene is less likely to be mistaken for the
camera failure because all three conditions must be met:

- `PURPLE_RATIO_THRESHOLD` measures the combined red/blue dominance over the
  two green parities;
- `RED_SIDE_RATIO_THRESHOLD` requires the red parity to dominate green; and
- `BLUE_SIDE_RATIO_THRESHOLD` requires the blue parity to dominate green.

The repair runs in bounded row chunks to limit peak memory use. It:

1. removes the observed one-row phase error;
2. applies a calibrated lookup table to each RGGB parity;
3. records prematurely clipped green locations before gain correction;
4. reconstructs those green highlights from the repaired red/blue context;
5. blends strongly coloured and near-neutral highlight estimates across the
   configured highlight boundaries; and
6. copies a stable neighbouring row into the final row, whose source is lost
   by the phase correction.

The runtime and calibration engine share the detector, repair function,
highlight-boundary conversion, and defaults. There is no second correction
algorithm that can drift out of sync.

## Settings reference

All keys live below `IMAGE_ASI676MC_REPAIR`. In the web interface they appear
in the **ASI676MC purple-frame handling** card under **Config > Image**.

### Purple-frame options

| Web control | Key | Default | Purpose |
| --- | --- | ---: | --- |
| **Enable ASI676MC purple-frame handling** | `ENABLE` | `False` | Master safety switch. Leave off for unaffected cameras. |
| **Detect and exclude only** | `EXCLUDE_ONLY` | `True` | Detect, flag, and exclude purple frames without changing pixels. Disable only after reviewing calibration. |
| **Log every ASI676MC frame** | `LOG_EVERY_FRAME` | `False` | Log normal-frame checks at info level instead of debug level. Purple frames and failures are always logged prominently. |
| **Show purple-frame status in gallery** | `GALLERY_ENABLE` | `False` | Show repaired, excluded, and failed states and their filters. The excluded filter does not include manually excluded frames. Turning off the master feature also turns this option off. |
| **Save purple and following normal FITS for calibration** | `SAVE_DIAGNOSTIC_FITS` | `False` | Save the untouched purple frame and its immediately following compatible frame as the preferred low-disk evidence. A successor with different capture/layout metadata breaks the group and is not retained as its reference. |
| **Also save the preceding normal FITS** | `SAVE_PRECEDING_FITS` | `False` | Cache the immediately preceding normal FITS and save it when the next compatible frame is purple. Requires the parent diagnostic option. |

### Advanced options

These numerical controls should normally be set by the calibration tool;
manual tuning is not recommended.

| Web control | Key | Default | Purpose |
| --- | --- | ---: | --- |
| **Overall purple-frame threshold** | `PURPLE_RATIO_THRESHOLD` | `1.5` | Combined purple signature threshold. |
| **Red-side purple-frame threshold** | `RED_SIDE_RATIO_THRESHOLD` | `1.15` | Red-side signature threshold. |
| **Blue-side purple-frame threshold** | `BLUE_SIDE_RATIO_THRESHOLD` | `1.75` | Blue-side signature threshold. |
| **Detection sample step** | `SAMPLE_STEP` | `32` | Even Bayer-preserving interval used by live detection. |
| **Clipped-highlight brightness level** | `SOURCE_SATURATION_THRESHOLD` | `65000` | Faulty-stream level treated as clipped for green reconstruction. |
| **Red repair gain** | `GAIN_R` | `0.91004` | Repair gain for the red parity. |
| **First green repair gain** | `GAIN_G1` | `1.68652` | Repair gain for the first green parity. |
| **Second green repair gain** | `GAIN_G2` | `1.09238` | Repair gain for the second green parity. |
| **Blue repair gain** | `GAIN_B` | `0.59537` | Repair gain for the blue parity. |
| **Highlight correction start** | `HIGHLIGHT_BLEND_START_RATIO` | `0.55` | Red/blue balance at which highlight blending begins. |
| **Highlight correction end** | `HIGHLIGHT_BLEND_END_RATIO` | `0.75` | Red/blue balance at which the near-neutral estimate takes over. |
| **Rows processed at once** | `CHUNK_ROWS` | `128` | Even number of rows processed at a time during repair. |

A full calibration derives only the four parity gains, the clipped-highlight
brightness level, and the two highlight blend ratios. A preliminary analysis
may suggest detection thresholds, but it never changes them automatically.
Sample step, chunk size, and operational switches are never derived.

## Collecting calibration FITS

Calibration needs the untouched purple mosaic and at least one compatible
normal reference for each purple frame. A normal/purple/normal triplet is
preferred because the two normal frames can be averaged; a normal/purple pair
is also valid. The final evidence must include at least seven purple frames,
seven distinct normal references, and two meaningfully different exposure
settings.

### Recommended: low-disk diagnostic capture

Enable **Save purple and following normal FITS for calibration**. For each
detected purple frame, indi-allsky copies the original camera FITS before a
temporary repaired array can affect later processing, then saves the
immediately following compatible frame. This option adds no persistent
full-frame memory cache.

Optionally enable **Also save the preceding normal FITS**. The image worker
keeps up to one untouched normal FITS byte string per active camera and writes
it only if the next compatible frame is purple. If that normal frame was
already saved as the following member of an earlier group, indi-allsky reuses
the database FITS rather than retaining a duplicate byte string. The cache
advances after each normal frame and is discarded after a purple, skipped, or
incompatible frame.

Each diagnostic FITS is a normal database-managed FITS asset with role
metadata:

- `preceding` - normal frame immediately before the purple frame;
- `bad` - untouched purple frame; or
- `following` - frame immediately after the purple frame.

One physical FITS can carry more than one role when consecutive groups share a
frame. Diagnostic files use the normal FITS upload destinations, retention
setting, and expiration task. They can be downloaded from the standard Image
Viewer when the relevant download controls are available.

Diagnostic and standard FITS saving remain independent. If both paths select
the same exposure, both files are retained: the diagnostic asset preserves the
untouched input, while the standard asset follows the normal processing
settings.

### Fallback: standard FITS capture

If diagnostic saving does not catch the purple frame, temporarily set standard
FITS saving to **Every Image**. A periodic interval cannot reliably capture a
random failure.

In **Detect and exclude only** mode, standard FITS retain the original mosaic
and can provide calibration evidence. When repair is active, standard FITS are
written from the already repaired image and may no longer contain the failure;
use diagnostic saving when untouched evidence is required.

The same distinction applies when **Save FITS Pre-Calibration** is enabled.
ASI676MC handling runs before the optional pre-dark save point, so
"pre-calibration" refers to dark-frame calibration, not purple-frame handling.
In **Detect and exclude only** mode, both standard save paths retain the
original mosaic.

The settings and calibration pages show a combined capture outlook based on
the current repair and FITS options. That message describes future captures;
saved-FITS discovery judges existing files by their actual metadata and
availability.

## Calibration tool

The tool appears under **Tools > Fix ASI676MC purple frames** only when:

- the ASI676MC master switch is enabled;
- a visible local camera is positively identified as an ASI676MC; and
- the current user can save settings on the Config page.

Direct calibration URLs enforce the same conditions. With normal
authentication, the user must be an administrator. With `LOGIN_DISABLED`, the
tool follows the anonymous access policy used by Config while still separating
private calibration ownership with a browser-specific token.

### Multiple ASI676MC units

The camera selector binds evidence, session ownership, and save-time identity
checks to one physical camera record. It does not create a per-camera repair
profile. `IMAGE_ASI676MC_REPAIR` remains one installation-wide configuration
block, so every ASI676MC on that installation uses the same applied thresholds
and repair constants.

That design suits the usual one-camera installation. An installation that
regularly swaps between or processes data from multiple physical ASI676MC
units must keep one shared profile or recalibrate when the active unit changes.
A per-camera repair profile would require configuration and runtime changes,
not only a calibration-page change.

### Choose an evidence source

The page provides two input paths. **Use saved FITS** is the preferred path for
database-managed evidence; **Upload a FITS collection** accepts a collection
that the user selected manually.

#### Use saved FITS

Choose a target of 7 to 30 purple-frame groups. The background job enumerates
the complete configured FITS retention period, inspects every eligible row,
and stages up to the requested number of usable groups. If fewer than seven
groups exist, it reports that the retained archive was exhausted. Progress
covers catalog enumeration, current-detector checks, missed-purple population
discovery, fitting, and validation. **Cancel search** remains available during
inspection and staging.

Existing diagnostic roles and purple-frame database flags provide context but
do not decide admission or inferred populations. This allows discovery to find
failures outside the configured detector thresholds. Untouched diagnostic RAW
FITS and standard FITS from **Detect and exclude only** remain eligible and can
be mixed as pairs or triplets. A standard FITS associated with a successfully
repaired frame is excluded because it contains the corrected mosaic.

New FITS rows store the three measured detector ratios as small,
threshold-independent metadata. Discovery can reclassify those captures
without decoding their full images. Older rows without cached ratios remain
eligible and are inspected directly; successful measurements are backfilled in
batches for later searches. A lightweight header check still rejects a
repaired `ASI676FX` FITS. Database discovery can also open indi-allsky's
gzip-compressed FITS.

The database row's validated camera binding supplies the ASI676MC identity
when a file's camera headers are absent or generic. An explicit conflicting
camera identity remains authoritative and is rejected. Missing, corrupt,
repaired, or incompatible files are skipped and summarized rather than
silently shortening the search horizon.

The 200-FITS and 2.5-GiB limits apply to the final purple/reference evidence
set, not to catalog discovery. Only selected evidence enters the private
session. The saved-FITS path stages up to three groups beyond the requested
count as validation reserves. If a group passes the main repair checks, but the
complete repair is less than ten percent better than a simple colour-only
correction, that inconclusive group is set aside, a reserve is promoted, and the
fit is repeated. The complete repair must still outperform colour-only
correction; otherwise calibration fails. The group count is reduced only when
no reserve remains, and never below the seven-group minimum.

A hard link keeps staged evidence stable without a second copy; where hard
links are unavailable, the tool makes a private copy. It never uses a symbolic
link whose target could change after selection. If a selected source disappears
during staging, that file is skipped and the remaining evidence is still
evaluated.

Cancellation removes only private links, copies, or partial copies. Source
FITS pixels and headers are never changed. The only durable discovery update
is the threshold-independent ratio cache on successfully inspected legacy
rows.

#### Upload a FITS collection

Select 14 to 80 uncompressed `.fit`, `.fits`, or `.fts` files. The browser
uploads them sequentially so a Raspberry Pi does not need to buffer the full
collection in one request. Browser and server enforce these limits:

- 80 files per session;
- 256 MiB per file; and
- 2 GiB total per session.

Fourteen files are enough to start analysis because the tool cannot know the
populations before reading them; the count does not guarantee a result.
Calibration or threshold discovery still needs seven likely purple frames and
distinct compatible normal evidence. Extra unmatched files are ignored only
when the remaining collection meets all evidence rules.

Uploads are bound to the selected, currently available ASI676MC by database
ID, UUID, and detected device name. This also provides a narrow camera-bound
legacy compatibility path for standard FITS written with indi-allsky's default
`INSTRUME=indi-allsky` header. If all camera-bearing headers are absent or
generic, the bound identity may be used after every RAW-layout check passes. An
explicitly different camera is always rejected. Standalone and non-camera-bound
uses remain strict, and the result and text report state how many uploaded
files used this legacy identity path.

The page checks the browser features required for multi-file selection,
sequential requests, cancellation, progress polling, and result restoration.
It displays a blocking explanation when those features are unavailable. An
upload can be cancelled while it is active, and a server-side marker prevents
a late request from reviving the cancelled session.

### Progress, cancellation, and restoration

After either source passes its input checks, the setup area is replaced by a
compact progress view with the current stage, progress bar, status detail, and
cancel action. The page scrolls to that view once; polling updates do not keep
moving the page. Cancellation stops discovery or private staging at its next
safe checkpoint, cancels a queued job, or asks a running worker to stop
cooperatively, then restores the input controls.

A failed analysis stays in the compact progress view with its full safe error
message and a **Try again** action. **Try again** removes the finished failed
session and returns to setup. Reloading while a retained calibration is
queued, running, complete, failed, or waiting to be reset restores its current
view.

### How analysis works

Every usable frame must pass the same core checks before it can contribute to
either outcome. The engine requires:

- explicit ASI676MC identity, or the selected camera's identity through the
  camera-bound legacy path described above;
- `BAYERPAT=RGGB`, an even-sized RAW16 mosaic, 1x1 binning, and zero Bayer
  offsets;
- finite positive exposure, finite non-negative gain, valid timestamps, and
  decoded-size limits; and
- exact frame-shape matching within each purple/reference group.

Primary and image-extension headers are merged. A repaired FITS marked
`ASI676FX` or a file with conflicting camera identity is rejected. Every
accepted frame is classified by the same signature implementation used during
live capture.

The decision path then proceeds in this order:

1. Apply the configured detector to every supplied frame. The tool never
   silently replaces configured thresholds.
2. If at least seven detected purple frames have compatible adjacent normal
   evidence, continue to normal calibration.
3. If fewer than seven are detected, or one configured threshold sits outside
   an otherwise clean normal/purple gap, check whether all three ratios form
   two strong, consistently ordered populations.
4. Return either a full calibration, a preliminary detection-threshold
   suggestion, or a safe failure. Inferred labels are never used to fit repair
   constants in the same run.

Database flags and filenames do not decide inferred populations. A threshold
suggestion is allowed only when both populations contain at least seven FITS,
every ratio has a clean gap of at least ten percent, likely purple frames have
compatible adjacent normal references, and at least two exposure settings are
represented.

For a full calibration, every used purple frame needs at least one compatible
normal reference. The complete evidence must also provide:

- at least seven distinct normal references;
- clean normal/purple signature separation;
- sufficient unsaturated samples for each Bayer parity;
- sufficient clipped-highlight evidence for both blend boundaries;
- plausible gains with low between-pair median absolute deviation; and
- a repair materially closer to nearby normal evidence than both the original
  frame and a colour-only correction.

Normal references that change too much across a two-sided triplet are rejected
at the affected sample locations, limiting the influence of cloud, aircraft,
or other transient content. Robust medians and median-absolute-deviation
filtering reduce the effect of remaining outliers.

The engine then estimates the four parity gains, finds the premature clipping
plateau, searches the supported highlight-boundary grid, and validates the
rounded values by running every matched purple frame through the live repair
path. Calibration fails if any repaired frame still matches the failure
signature.

### Possible outcomes

#### Full calibration

A successful result shows the derived and currently configured values, matched
purple and normal counts, pair/triplet and exposure coverage, signature ranges,
unused or rejected evidence, warnings, and whether the result effectively
matches the configuration within a small tolerance.

Two-sided evidence is considered complete enough when at least 90 percent of
matched purple frames belong to normal/purple/normal triplets. Below that
guideline, the result recommends gathering more complete groups. Reused normal
references remain a separate confidence warning.

A calibration remains successful when a configured detection threshold sits
within fifteen percent of either edge of its observed safe gap. A dedicated
table shows the current value, normal/purple range, and midpoint, while the
guidance recommends collecting more varied evidence before changing that
threshold. Repair constants remain valid.

#### Detection settings need adjustment

This is a preliminary result, not a calibration. It contains no repair
constants and changes no settings during analysis. The repair-value table is
hidden. Instead, the page shows current and recommended detection thresholds,
their observed safe intervals, population and adjacency evidence, and an
instruction to review the files and rerun.

When representative FITS can be rendered, the page shows up to two likely
purple frames and two likely normal frames for both uploaded and saved
collections. The images come from the original, unrepaired FITS and use one
brightness stretch across all three colour channels so the colour difference
remains visible. Previews are best-effort visual aids. If one cannot be
created, the other previews and the authoritative filename, capture-time, and
ratio table remain available; the valid threshold result is not discarded.

The user must confirm, after checking the previews when available plus the
filenames and capture times, that the files listed as likely purple show the
actual camera failure. Saving stays blocked until the confirmation is checked.
A user who can save Config may then choose **Save detection settings**. Only
fields marked Change recommended are saved; a configured threshold already
inside its safe gap is retained instead of being replaced by a cosmetically
different midpoint. Select **Start over** and rerun calibration after saving.

#### Analysis cannot establish a safe result

Overlapping, insufficient, or inconsistently ordered populations produce a
plain-language explanation rather than an unsafe suggestion. The same applies
when evidence validation or repair fitting cannot meet its safety checks. No
confirmation is offered and no settings are changed. The retained failure view
shows what to check before selecting **Try again**.

### Report and applying values

**Download details** produces a text report for both full and preliminary
results. It records the evidence source, quality assessment, values,
configuration comparison from the start of the run, warnings, cleanup outcome,
and recommended next actions. It never exposes private staging paths. The
filename begins with local completion time in
`YYYY-MM-DD_HH-MM-SS_asi676mc_calibration_report.txt` format.

Known rejection and safety-check reasons are translated into concise
explanations with corrective actions. If every selected file is rejected, the
failure view groups reasons and affected file counts. Unknown exceptions stay
private and direct the user to the indi-allsky log. The background task list
uses the same safe wording; if its short status cannot contain every reason, it
directs the user to the retained failure view.

For a full result, **Save calibration values** writes only the seven derived
repair keys through the normal configuration-save mechanism and queues an
application reload. It refuses the update if the configuration or selected
ASI676MC identity changed after the run began. Operational switches and
detection thresholds remain unchanged.

For a preliminary result, **Save detection settings** can write only the
explicitly recommended threshold keys after population confirmation. It cannot
write repair constants.

Results are retained under unguessable session IDs so the user can leave and
return. Per-tab state plus a shared list prevents tabs from replacing each
other's run; after one run is cleared, the next retained run is restored.
Transient polling failures retry without discarding the handle. The browser
stores no FITS data or calibration values, and every result, report, discard,
and apply request rechecks ownership and camera binding. **Start over**
discards the retained result.

### Session storage and cleanup

Private sessions live below the non-public Flask instance directory, or below
`ASI676MC_CALIBRATION_FOLDER` when explicitly configured. Manifest and result
files are written atomically because web and worker processes may access them
at the same time.

CPU-heavy fitting and full-resolution validation run on a dedicated serial
calibration thread in the low-priority video-worker process. The normal video
queue remains available for timelapse and keogram work. Cross-process locks
protect session changes, and a queued job can be claimed only once. Each owner
may have two active sessions; the installation may have four.

Saved-FITS searches, queued jobs, population analysis, pairing, and fitting can
all be cancelled at bounded checkpoints. Uploads and queued jobs become stale
after 30 minutes; a running job is failed after two hours without a worker
heartbeat. These safeguards prevent abandoned work from occupying a session
quota indefinitely.

Cleanup depends on the source:

- uploaded FITS are deleted immediately after success or failure;
- private hard links or copies from database discovery are deleted
  immediately, while source FITS remain untouched; and
- cancellation and reset remove the session's private inputs directly.

If a crash, power loss, or unavailable filesystem interrupts immediate
cleanup, the regular expiration task removes sessions older than seven days.
That fixed session retention is independent of database FITS retention;
database FITS and diagnostic role links continue to follow normal indi-allsky
expiration rules.

## Troubleshooting

**The tool is absent from the menu**

Connect a visible local ASI676MC, enable **Enable ASI676MC purple-frame
handling**, and use an account that can save Config. When login is disabled,
the tool follows Config's open-access policy.

**Fewer than 14 eligible saved FITS are found**

Current settings describe future capture, not the retained archive. Existing
purple frames may have expired or may never have been saved untouched. Prefer
diagnostic FITS and collect more events. If diagnostics do not catch the
failure, temporarily use **Detect and exclude only** with standard FITS saving
set to every image.

**Files upload but the collection is rejected**

Confirm that the collection contains uncompressed ASI676MC RAW16 RGGB files,
seven purple events with compatible adjacent normal references, two exposure
levels, and visible clipped highlights. Extra files do not compensate for a
missing minimum. Default indi-allsky standard FITS with only the generic
`INSTRUME=indi-allsky` header are accepted through the camera-bound legacy path;
an explicit different-camera header is not.

The retained error groups known rejection reasons and says what to correct. If
it names a detection ratio, compare the likely-normal and likely-purple
evidence. Clean populations produce a preliminary suggestion; unclear
populations fail safely. Do not change a threshold unless the listed likely
purple files show the actual camera failure.

**No preview images appear with a threshold suggestion**

Use the complete filename, capture-time, and ratio table to confirm the
populations. A preview is optional and does not replace or weaken the evidence
checks behind the suggestion.

**The report time differs from UTC**

Browser and report timestamps intentionally use local time, including timezone
name and UTC offset where space permits. Private manifests retain UTC so
expiration and communication between web and worker processes remain
unambiguous.

**Saving values is refused**

The indi-allsky configuration changed after the run began, the bound camera is
no longer the same local ASI676MC, or the user cannot save Config. Start a new
calibration against the current configuration and camera.

**Repair validation fails during capture**

The original frame is preserved. Collect its untouched diagnostic group and
recalibrate; do not loosen detection thresholds merely to suppress the
warning.

## Maintainer map

| File | Responsibility |
| --- | --- |
| `indi_allsky/config.py` | Conservative new-install defaults, including disabled handling and **Detect and exclude only** mode. |
| `indi_allsky/asi676mc.py` | Authoritative settings normalization, signature detection, repair, validation, metadata, and diagnostic-role helpers. |
| `indi_allsky/processing.py` | Runtime eligibility checks, **Detect and exclude only** behavior, repair invocation, logging, and actionable notifications. |
| `indi_allsky/image.py` | Untouched diagnostic FITS capture, optional preceding-frame cache, database records, and rendered-image metadata. |
| `indi_allsky/asi676mc_calibration_engine.py` | FITS inspection, matching, evidence policy, numerical fitting, and validation through the live repair path. |
| `indi_allsky/asi676mc_calibration.py` | Private sessions, uploads, database discovery/staging, population previews, cleanup, user guidance, result comparison, and text reports. |
| `indi_allsky/video.py` | Dedicated serial calibration consumer, retained-FITS database access and ratio-cache backfill, plus seven-day session cleanup fallback. |
| `indi_allsky/flask/forms.py` | Settings validators, calibration controls, saved-FITS lookup, viewer assets, and gallery filtering. |
| `indi_allsky/flask/views.py` | Authenticated endpoints, task queueing, result/report access, and configuration apply/reload. |
| `indi_allsky/flask/base_views.py` and `templates/base.html` | Context-aware Tools-menu visibility in the current navigation. |
| `indi_allsky/flask/templates/config.html`, `config/image.html`, and `config/asi676mc.html` | Configuration save integration, responsive settings card, and contextual guidance. |
| `indi_allsky/flask/templates/asi676mc_calibration.html` | Calibration setup/progress/result transitions, population previews, cancellation, reports, reset, and browser capability checks. |
| `indi_allsky/flask/templates/gallery.html` | Optional repair/exclusion badges, outlines, and status-specific filtering. |
| `indi_allsky/flask/templates/imageviewer.html` | Diagnostic preceding/purple/following FITS downloads. |
| `tests/image/test_asi676mc_repair.py` | Detection, repair, validation, metadata, and diagnostic helper coverage. |
| `tests/core/test_asi676mc_calibration_engine.py` | FITS inspection, matching, fitting, evidence policy, and shared-runtime coverage. |
| `tests/flask/test_asi676mc_web_calibration.py` | Sessions, cleanup, discovery, guidance, reports, and web workflow coverage. |

Run the focused tests from the repository root:

```text
pytest tests/image/test_asi676mc_repair.py tests/core/test_asi676mc_calibration_engine.py tests/flask/test_asi676mc_web_calibration.py
```

When changing correction math, update `indi_allsky/asi676mc.py` first. The
calibration engine must continue to call that implementation for classification
and final validation. When changing a setting or diagnostic role, trace it
through defaults, form validation, view persistence, help text, metadata,
report output, and tests so the complete feature remains coherent.
