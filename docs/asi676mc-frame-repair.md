# ASI676MC purple-frame handling and calibration

## Purpose and safety boundary

Some ZWO ASI676MC cameras occasionally deliver a RAW16 RGGB mosaic with a
strong purple cast. This feature detects that specific failure, can flag the
affected frame for exclusion without modifying it, and can optionally repair
it before the normal indi-allsky image pipeline continues.

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
purple frame, preserves its original pixels, and excludes it from standard
timelapses. Pixel repair begins only after the user explicitly disables Exclude
Only.

The existing indi-allsky `exclude` flag is not honored by every derived
timelapse-style output. This feature deliberately uses that standard flag
without changing its wider propagation; non-standard outputs may still include
an Exclude Only frame.

## Runtime processing

Purple-frame handling runs immediately after indi-allsky opens the camera FITS
and before dark-frame calibration, debayering, stacking, or standard FITS
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
| `excluded` | A purple frame was detected in Exclude Only mode; pixels were retained and the frame was excluded from standard timelapses. |
| `repaired` | A purple frame was repaired and passed post-repair validation. |
| `validation_failed` | Repair output still matched the failure; the original frame was retained and excluded from standard timelapses. |
| `skipped` | The camera or RAW layout did not meet the safety boundary, or the configuration was invalid. |

The metadata also retains the available before/after ratios, timing, and reason
text. Gallery decoration is optional and does not affect processing.

A skipped check or failed post-repair validation also creates a Camera
notification. The first occurrence appears immediately; identical notification
types are suppressed for two hours so an incompatible capture stream cannot
flood the notification list. Normal frames, expected Exclude Only detections,
and successful repairs remain visible through their usual logs and gallery
metadata without generating notifications.

## Detection and repair model

The detector sparsely samples the four Bayer parities while preserving RGGB
alignment. It uses three ratios so a naturally magenta scene is less likely to
be mistaken for the camera failure:

- `PURPLE_RATIO_THRESHOLD` measures the combined red/blue dominance over the
  two green parities;
- `RED_SIDE_RATIO_THRESHOLD` requires the red parity to dominate green; and
- `BLUE_SIDE_RATIO_THRESHOLD` requires the blue parity to dominate green.

All three conditions must be met.

The calibration workflow starts with the configured thresholds; it never
silently replaces them. It first checks every supplied frame with the live
detector. Seven detected purple frames with adjacent normal evidence take the
normal calibration path. If the detector identifies fewer than seven, the tool
checks whether all three ratios form two strong, consistently ordered
populations. It uses the same preliminary result when the three-way detector
finds enough frames but one individual threshold lies outside that ratio's
clean normal/purple gap. Threshold suggestions appear only when both
populations contain at least seven FITS, every ratio has a clean gap of at
least ten percent, likely purple frames have compatible adjacent normal
references, and at least two exposure settings are represented. Database flags
and filenames do not decide inferred populations.

Threshold discovery is a preliminary outcome, not calibration. It derives no
repair constants and changes no settings during analysis. The user must confirm
that the higher-ratio population represents the expected purple-frame failure.
A user who can save settings on the Config page can then select **Apply
thresholds and reload**, or enter only the recommended thresholds in Image
Settings, and rerun calibration. Saving is blocked until the user confirms,
after reviewing listed filenames and capture times, that the higher-ratio
population is the actual failure rather than an ordinary scene regime.
A configured threshold already inside an observed safe gap is retained rather
than replaced by a cosmetically different midpoint. Overlapping or
inconsistently ordered populations produce an explanation instead of an unsafe
suggestion.

When calibration succeeds but a configured threshold sits within fifteen
percent of either edge of its observed normal/purple gap, the repair constants
remain valid. The result page and report show the measured ranges and midpoint,
but recommend collecting more varied evidence and rerunning before changing
that threshold.

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
In the web interface they appear together in the dedicated **ASI676MC RAW16
Purple-frame Handling** card under **Config > Image**. The card follows the
same responsive layout, controls, validation, and save permissions as the
rest of the current configuration interface.

| Key | Default | Purpose |
| --- | ---: | --- |
| `ENABLE` | `False` | Master safety switch. Leave off for unaffected cameras. |
| `EXCLUDE_ONLY` | `True` | Detect, flag, and exclude purple frames without changing pixels. Disable only after reviewing calibration. |
| `LOG_EVERY_FRAME` | `False` | Log normal-frame checks at info level instead of debug level. Purple frames and failures are always logged prominently. |
| `GALLERY_ENABLE` | `True` | Show repair/exclusion status in the gallery and enable repaired, purple-frame-excluded, and validation-failed filters. |
| `SAVE_DIAGNOSTIC_FITS` | `False` | Save the untouched purple frame and its following frame as the preferred low-disk calibration evidence. |
| `SAVE_PRECEDING_FITS` | `False` | Also cache the immediately preceding normal FITS and save it when the next compatible frame is purple. Requires the parent diagnostic option. |
| `PURPLE_RATIO_THRESHOLD` | `1.5` | Combined purple signature threshold. |
| `RED_SIDE_RATIO_THRESHOLD` | `1.15` | Red-side signature threshold. |
| `BLUE_SIDE_RATIO_THRESHOLD` | `1.75` | Blue-side signature threshold. |
| `SAMPLE_STEP` | `32` | Even Bayer-preserving interval used by live detection. |
| `SOURCE_SATURATION_THRESHOLD` | `65000` | Faulty-stream level treated as clipped for green reconstruction. |
| `GAIN_R` | `0.91004` | Repair gain for the red parity. |
| `GAIN_G1` | `1.68652` | Repair gain for the first green parity. |
| `GAIN_G2` | `1.09238` | Repair gain for the second green parity. |
| `GAIN_B` | `0.59537` | Repair gain for the blue parity. |
| `HIGHLIGHT_BLEND_START_RATIO` | `0.55` | Red/blue balance at which highlight blending begins. |
| `HIGHLIGHT_BLEND_END_RATIO` | `0.75` | Red/blue balance at which the near-neutral estimate takes over. |
| `CHUNK_ROWS` | `128` | Even number of rows processed at a time during repair. |

After detection is established, the web calibration tool derives only the four
parity gains, saturation threshold, and two highlight blend ratios. Detection
thresholds remain deliberate user-controlled settings even when preliminary
analysis suggests them; sample step, chunk size, and operational switches are
never derived.

## Collecting calibration evidence

Calibration needs the untouched purple mosaic and at least one compatible
normal reference. A normal/purple/normal triplet is preferable because the two
normal frames can be averaged, but a normal/purple pair is valid.

Diagnostic capture is the preferred strategy. Standard FITS should be used as
calibration evidence only when diagnostic saving does not catch the purple
frame, or retained independently when the user explicitly wants standard FITS
for another purpose.

### Low-disk diagnostic capture

Enable **Save Bad and Following RAW FITS**. For each detected purple frame,
indi-allsky copies the original camera FITS before the temporary repaired array
can affect later processing, then saves the immediately following ingested
frame. This mode adds no persistent full-frame memory cache.

Optionally enable **Also Save Preceding RAW FITS**. The image worker then keeps
up to one untouched, normal FITS byte string per active camera in memory. It
writes that cached frame only if the next compatible frame is purple. If the
normal frame was already saved as the following member of an earlier group,
indi-allsky reuses that database FITS and does not retain a duplicate byte
string. The cache is advanced after each normal frame and discarded after a
purple, skipped, or incompatible frame. The option improves evidence quality
at the cost of up to one full FITS of memory per active camera and one
additional saved FITS per purple event.

Each diagnostic FITS is a normal database-managed FITS asset with role metadata:

- `preceding` - normal frame immediately before the purple frame;
- `bad` - untouched purple frame; or
- `following` - frame immediately after the purple frame.

One physical FITS can carry more than one role when consecutive groups share a
frame. Diagnostic files use the normal FITS upload destinations, retention
setting, and expiration task. They can be downloaded from the standard Image
Viewer when the relevant download controls are available.

Standard and diagnostic saving remain independent when both are enabled. If
both paths select the same exposure, both files are retained because the
diagnostic asset preserves the untouched input while the standard asset follows
the normal processing settings. Leave standard FITS off for the lowest disk
use unless those standard files are wanted for another purpose.

### Standard FITS fallback capture

If diagnostic saving does not catch the purple frame, temporarily set standard
FITS saving to **Every Image** to collect complete normal/purple/normal
sequences. A periodic interval cannot reliably capture a randomly occurring
failure.

In **Exclude Only** mode, standard FITS still contain the original mosaic and
can therefore provide this fallback evidence.

When repair is active, standard FITS are written from the already repaired
image and may no longer contain the original failure. Use the diagnostic FITS
option if untouched purple evidence is required.

This also applies when **Save FITS Pre-Calibration** is enabled. ASI676MC
handling runs immediately after the camera FITS is opened, before the optional
pre-dark save point; "pre-calibration" refers to dark-frame calibration, not to
purple-frame handling. In Exclude Only mode, both standard save paths retain
the original mosaic.

The settings and calibration pages display a combined capture outlook based on
the current repair and FITS options. That message describes future captures;
the discovery process judges existing files by their actual metadata and
availability.

## Calibration tool

The tool appears in the Tools menu only when the ASI676MC master switch is
enabled, a visible local camera is positively identified as an ASI676MC, and
the current user can save settings on the Config page. Direct calibration URLs
enforce the same three conditions. With normal authentication that means an
administrator. With `LOGIN_DISABLED`, the same anonymous browser access
allowed by Config is used; private calibration ownership is still separated
by a browser-specific token.

### Multiple ASI676MC units

The camera selector binds uploaded or discovered evidence, session ownership,
and save-time identity checks to one physical camera record. It does not create
a per-camera repair profile. `IMAGE_ASI676MC_REPAIR` is one installation-wide
configuration block, so applied thresholds and repair constants are used by
every ASI676MC processed with that configuration.

This is appropriate for the usual one-camera installation. An installation
that regularly swaps between, or processes data from, multiple physical
ASI676MC units must currently keep one shared profile or recalibrate when the
active unit changes. Per-camera calibration profiles are possible future work
and would require a configuration and runtime design change rather than a
calibration-page-only change.

The page supports two input paths.

After either path passes its input checks and starts, the long setup area is
replaced by a compact progress view containing the current stage, progress bar,
status detail, and cancel action. The page scrolls to that view once, but later
polling updates do not move the page again. Successful completion replaces the
progress view with the result. Cancellation restores the original input
controls. A failed analysis remains on the compact progress view, where the
complete error is visible and the cancel action is replaced by **Reset / try
again**. Reset removes the finished failed session and restores the inputs.
Reloading the page while a retained calibration is queued, running, or waiting
to be reset opens directly in its current compact view.

### Manual multi-file upload

The file picker accepts all selected FITS at once. The browser uploads them
sequentially so a Raspberry Pi does not need to buffer a large collection in
one request. Limits are enforced on both browser and server:

- 200 files per session;
- 256 MiB per file; and
- 2 GiB total per session.

Select at least 14 files. That count starts analysis because the tool cannot
know the populations before inspecting the data; it does not guarantee a
result. Calibration or threshold discovery still needs at least seven likely
purple frames with distinct compatible normal evidence. Unmatched extra files
are ignored only when the remaining collection meets the strict evidence
rules.

The page requires modern JavaScript features used for multi-file selection,
streamed requests, cancellation, progress, polling, and result restoration. It
checks these capabilities on load and displays a blocking explanation if the
browser cannot provide them.

Manual uploads are bound to the selected, currently available ASI676MC by its
database ID, UUID, and detected device name. This also provides a narrow
camera-bound legacy compatibility path for standard FITS written with
indi-allsky's default `INSTRUME=indi-allsky` header. When all camera-bearing
headers are absent or generic, the tool may use the bound ASI676MC identity
after every RAW-layout check passes. A file that explicitly names another
camera is always rejected; the session identity never overrides conflicting
FITS metadata. Standalone and non-camera-bound uses remain strict. The result
and text report disclose how many uploaded files used this legacy identity
path.

The cancel action aborts an active upload, stops saved-FITS discovery or
private staging at its next safe checkpoint, cancels a queued job, or asks a
running worker to stop cooperatively. A server-side marker also prevents a
late request from reviving a cancelled session.

### Discover saved FITS

Automatic discovery searches database-managed FITS for the selected ASI676MC.
The user chooses a target of 7 to 100 purple-frame groups rather than a raw file
limit. Discovery starts with the newest evidence inside the configured FITS
retention period:

- when at least seven database-marked purple frames have compatible adjacent
  normal FITS, it stages the newest complete groups up to the target; or
- with zero to six usable marked groups, three FITS per requested group form
  the initial search target. The worker checks for an actionable result as it
  progresses, so it may stop earlier; otherwise it continues newest-first
  through the bounded newest retained evidence set.

The second path intentionally ignores the target as a stopping limit. That is
necessary when the current detector missed every purple frame and their random
positions are unknown. The live progress display reports whether the worker is
checking the current detector, searching for missed high-ratio frames, fitting,
or validating.

Existing diagnostic roles and purple-frame database flags select the compact
path only when they supply at least seven complete groups. Otherwise they are
context rather than admission requirements. This is important when a camera's
failure ratios fall outside the configured detector thresholds. The only data
deliberately excluded before inspection is a standard FITS associated with a
successfully repaired frame, because it contains the corrected mosaic.
Untouched diagnostic RAW FITS and standard FITS from Exclude Only remain
eligible. Pairs and triplets can be mixed in one run.

Newly saved FITS database rows retain the three measured detector ratios as
small, threshold-independent metadata. A progressive search can reclassify
those captures against current settings without decoding every full image.
Older FITS without those stored ratios remain eligible for direct inspection;
when their camera headers are absent or generic, the selected database row's
already validated camera binding supplies the ASI676MC identity. A header that
explicitly identifies another camera remains authoritative and is rejected.
The result and report disclose how many saved FITS required this legacy
fallback. Only the purple and adjacent normal FITS selected for numerical
fitting are necessarily decoded after discovery.

Database discovery queries at most 600 newest candidate rows, then bounds
grouping and staging to 200 FITS and 2 GiB. This prevents a large retained
archive with no bad frames, or only bad frames, from creating unbounded or
quadratic work. A hard link keeps the selected content stable without a second
copy. If hard links are unavailable, the tool makes a private copy; it never
uses a symbolic-link fallback whose target could change after selection.
The browser reserves a camera-bound private session before discovery begins,
so **Cancel saved-FITS search** is available throughout database inspection and
staging. Cancellation removes only the session's private hard links, copies,
or partial copy; database rows and their source FITS are never changed.

## Evidence validation and fitting

Before fitting, the engine opens FITS through the Astropy support already used
by indi-allsky. Primary and image-extension headers are merged. It requires an
explicit ASI676MC identity or, for camera-bound manual upload and saved-FITS
discovery, the selected ASI676MC identity when legacy headers are absent or
generic. This fallback changes only the source of the camera name. It still
requires `BAYERPAT=RGGB`, RAW16 even dimensions, 1x1 binning, zero Bayer
offsets, finite positive exposure, finite non-negative gain, valid timestamps,
decoded-size limits, and exact frame-shape matching within each
purple/reference group. Repaired FITS marked `ASI676FX` and conflicting camera
identities are rejected. Every usable frame is classified with the same
signature implementation used by live processing.

A successful calibration requires:

- at least seven purple frames;
- at least seven distinct compatible normal references;
- at least one normal reference for every used purple frame;
- at least two exposure levels;
- clean separation between normal and purple signature ranges;
- sufficient unsaturated samples for each Bayer parity;
- sufficient clipped-highlight evidence to fit both blend boundaries;
- plausible gains with low between-pair median absolute deviation; and
- a repair materially closer to adjacent normal evidence than both the
  original and the best gain-only, no-row-shift counterfactual.

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

If the configured detector cannot establish the required populations, the
separate preliminary threshold-analysis policy described above runs before the
more expensive fitting stage. It never attempts repair fitting from inferred
labels in the same run.

## Results, report, and applying values

A successful results page shows:

- the derived value beside the current configured value;
- matched purple and normal counts;
- pair/triplet coverage, exposure coverage, and signature ranges;
- rejected or unused evidence and plain-language warnings; and
- whether the result effectively matches the current configuration within a
  deliberately small tolerance.

Two-sided evidence is considered complete enough when at least 90 percent of
the matched purple frames belong to good/purple/good triplets. The result note
still reports the exact coverage, but it does not ask for another complete
triplet above that guideline because the remaining one-sided evidence is
unlikely to change the calibration. Reused normal references remain a separate
confidence warning.

A preliminary threshold result instead shows current and suggested detection
values, each observed safe interval, population and adjacency evidence, and a
prominent instruction to review and rerun. The repair-value table is hidden.
For a user who can save settings on the Config page, **Apply thresholds and
reload** saves only fields marked Change recommended; it never saves repair
constants from a preliminary result. The result lists population filenames,
capture times, and ratios, and requires explicit higher-population
confirmation.

A normal calibration whose detector margin is narrow remains successful. Its
status area and a dedicated table identify the affected threshold, current
value, observed normal/purple gap, and midpoint so the warning is visible
without being confused with a failed calibration.

The downloadable text report is generated for the integrated workflow. It
records the evidence source, quality assessment, values, comparison with the
configuration at the start of calibration, warnings, cleanup outcome, and
recommended next actions. It never exposes private staging paths. Its download
name begins with the local completion time in
`YYYY-MM-DD_HH-MM-SS_asi676mc_calibration_report.txt` format so reports sort in
chronological order by filename. Known file-rejection and safety-check reasons
are translated into short explanations with a corrective action. If every
selected file is rejected, the failure view groups the reasons and shows how
many files each reason affected instead of replacing them with a generic
incompatibility message. Unknown exceptions remain private and direct the user
to the indi-allsky log. The background task list uses the same safe wording;
when its short status field cannot hold every grouped reason, it directs the
user back to the retained calibration failure view.

A user who can save settings on the Config page can select **Apply values and
reload**. The server writes only the seven derived keys, using the same
configuration-save mechanism as the settings page, then queues an application
reload. It refuses the update if the configuration or bound ASI676MC identity
changed after the run began. Operational switches such as Enable and Exclude
Only are never changed. Detection thresholds also remain unchanged after a
successful seven-value calibration; a narrow-margin notice directs the user
to change them manually if later evidence supports that choice. The
preliminary apply action permits only threshold keys explicitly marked for
change.

Results are retained in the browser by unguessable session IDs so a user can
visit another page and return. Per-tab state plus a shared list prevents tabs
from overwriting each other's run. Transient polling failures retry without
discarding the handle. The browser stores no FITS data or calibration values.
Every result, report, discard, and apply request rechecks ownership and camera
binding. **Reset / recalibrate** discards the retained result.

## Session storage and cleanup

Calibration sessions live below the non-public Flask instance directory, or
below `ASI676MC_CALIBRATION_FOLDER` when explicitly configured. Manifest and
result files are written atomically because web workers and the video worker
may read them concurrently.

The CPU-heavy fit and full-resolution validation run as a low-priority video
queue task rather than inside a web request. Session changes are protected by
cross-process locks, and a queued job can be claimed only once. Each owner may
have two active sessions and the installation may have four. Saved-FITS
searches, queued jobs, and running jobs can be cancelled at safe checkpoints;
stale queued jobs and workers with an old heartbeat are failed or cancelled so
the browser cannot poll forever.

Input cleanup is source-aware:

- browser-uploaded FITS are deleted immediately after the run succeeds or
  fails;
- private hard links or copies staged from the database are deleted
  immediately, while their database source FITS remain untouched; and
- cancellation and reset remove the session's private inputs directly.

If immediate cleanup is interrupted by a crash, power loss, or unavailable
filesystem, the regular expiration task removes calibration sessions older
than seven days. This fixed session retention is independent of database FITS
retention. Database FITS and diagnostic role links continue to use the normal
indi-allsky FITS expiration behavior.

## User workflow

1. Confirm that the ASI676MC actually produces the purple-frame failure.
2. Enable purple-frame handling and leave Exclude Only enabled.
3. Prefer low-disk diagnostic FITS. Leave standard FITS off unless they are
   independently wanted; use temporary standard FITS saving for every image
   only when diagnostics do not catch the purple frame. Enable preceding-frame
   caching only when the additional memory and disk use are acceptable.
4. Collect several purple events across at least two exposure levels.
5. Open **Tools > ASI676MC Calibration** as a user who can save settings on the
   Config page.
6. Discover saved FITS or select a multi-file upload.
7. If preliminary threshold suggestions appear, verify the populations, apply
   or manually edit only the recommended detection fields, reset the tool, and
   rerun.
8. Review the evidence summary, warnings, derived values, and current values.
9. Download the report if an audit copy is useful.
10. Apply the result only after it looks credible.
11. Disable Exclude Only to activate repair, then monitor gallery status and
    logs for validation failures.
12. Return FITS-saving options to the desired long-term disk-use policy.

## Troubleshooting

**The tool is absent from the menu**

Connect a visible local ASI676MC, enable the ASI676MC master switch in Config,
and use an account that can save settings on the Config page. When login is
disabled, the tool follows the same open access policy as Config.

**Fewer than 14 eligible saved FITS are found**

The current settings describe future evidence only. Existing purple frames may
have expired or may never have been saved as untouched FITS. Prefer diagnostic
FITS, collect new events, and try again. If diagnostics do not catch the purple
frame, use Exclude Only plus standard FITS for every image temporarily.

**Files upload but calibration rejects the collection**

Check that the collection contains uncompressed ASI676MC RAW16 RGGB files,
seven purple frames, a compatible adjacent normal frame for each, two exposure
levels, and visible clipped highlights. Extra unmatched files do not compensate
for a missing minimum. Default indi-allsky standard FITS with only the generic
`INSTRUME=indi-allsky` camera header are accepted through either manual upload
or automatic saved-FITS discovery when that path is bound to the selected
ASI676MC; an explicit different-camera header is not. The failure remains
beside the completed progress bar until **Reset / try again** is selected. The
message states the known reason and what to check; if several requirements
failed, it groups the affected file counts. If the error names a detection
ratio, compare the reported likely-normal and likely-purple populations. When
all three ratios have strong gaps, the tool may show preliminary threshold
suggestions instead of failing. Change a recommended threshold only after
confirming that the higher-ratio files are the expected camera failure, then
rerun calibration; the tool never changes detection thresholds during
analysis. A user who can save Config may save the recommended subset after
reviewing it.

**The report time differs from UTC**

This is intentional. Browser and text-report timestamps are shown in local
time, including the timezone name and UTC offset where space permits. Private
session manifests retain UTC internally so expiration and communication
between the web and background workers remain unambiguous.

**Calibration succeeds but applying values is refused**

The indi-allsky configuration changed after the run began, the bound camera is
no longer the same local ASI676MC, or the user cannot save Config. Start a new
calibration against the current configuration and camera.

**Repair validation fails during capture**

The original frame is preserved. Collect its untouched diagnostic group and
recalibrate; do not loosen detection thresholds merely to suppress the warning.

## Maintainer map

| File | Responsibility |
| --- | --- |
| `indi_allsky/config.py` | Conservative new-install defaults, including disabled handling and Exclude Only mode. |
| `indi_allsky/asi676mc.py` | Authoritative settings normalization, signature detection, repair, validation, metadata, and diagnostic-role helpers. |
| `indi_allsky/processing.py` | Runtime eligibility checks, Exclude Only behavior, repair invocation, logging, and actionable notifications. |
| `indi_allsky/image.py` | Untouched diagnostic FITS capture, optional preceding-frame cache, database records, and rendered-image metadata. |
| `indi_allsky/asi676mc_calibration_engine.py` | FITS inspection, matching, evidence policy, numerical fitting, and validation through the live repair path. |
| `indi_allsky/asi676mc_calibration.py` | Private sessions, uploads, database discovery/staging, cleanup, user guidance, result comparison, and text reports. |
| `indi_allsky/video.py` | Background calibration task and seven-day session cleanup fallback. |
| `indi_allsky/flask/forms.py` | Settings validators, calibration controls, saved-FITS lookup, viewer assets, and gallery filtering. |
| `indi_allsky/flask/views.py` | Authenticated endpoints, task queueing, result/report access, and configuration apply/reload. |
| `indi_allsky/flask/base_views.py` and `templates/base.html` | Context-aware Tools-menu visibility in the current navigation. |
| `indi_allsky/flask/templates/config.html`, `config/image.html`, and `config/asi676mc.html` | Configuration save integration, responsive settings card, and contextual guidance. |
| `indi_allsky/flask/templates/asi676mc_calibration.html` | Calibration setup/progress/result transitions, cancellation, reports, reset, and browser capability checks. |
| `indi_allsky/flask/templates/gallery.html` | Optional repair/exclusion badges, outlines, and status-specific filtering. |
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
