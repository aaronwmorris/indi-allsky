# ASI676MC frame repair and diagnostic FITS

This document records the custom ASI676MC repair first developed on
`dev/asi676mc-image-correction` and its web calibration integration developed
on `dev/asi676mc-web-calibration`. It is intended to give future maintainers
enough context to modify or remove the feature without disturbing the rest of
the indi-allsky pipeline.

## Change history

The feature was developed as the following commit series on top of upstream
commit `3d834018`:

| Commit | Purpose |
| --- | --- |
| `f9096757` | Add optional ASI676MC RAW16 frame correction |
| `7e965b26` | Add repair logging and gallery audit metadata |
| `684ad221` | Refine controls, camera gating, and timing |
| `0912d47c` | Reduce CPU and memory use on older Raspberry Pis |
| `4b7064b4` | Move the settings group to the bottom of the Image tab |
| `4e553308` | Save paired diagnostic FITS and add download controls |
| `35e2969f` | Add this maintenance and removal guide |
| `9909cc35` | Fix Image Viewer initialization with diagnostic downloads |
| `d5d75f2b` | Method 1: reconstruct jointly clipped green from the strongest red/blue channel |
| `f8cfbf22` | Keep diagnostic FITS downloads in the Image Viewer only |
| `02e321ec` | Method 2: reconstruct jointly clipped green from the red/blue mean |
| `ca835c21` | Method 3: use the adaptive factor-two highlight estimate |
| `5a6e3ab0` | Method 4: change the adaptive estimate to factor three |
| `c848d2fc` | Revert Method 4 and restore factor two |
| `01238f25` | Document the factor-two rollback |
| `71054af0` | Method 5: bound the factor-two-to-maximum transition |

Use `git show <commit>` for the exact historical patch. When the branch has
continued to evolve, use these commits as a map rather than blindly reverting
them.

## Runtime behavior

The repair is opt-in through `IMAGE_ASI676MC_REPAIR.ENABLE` and is gated by the
detected camera name. It only runs for an ASI676MC with supported RAW16 RGGB,
1x1-binned input. Detection and repair happen immediately after the input FITS
is opened and before calibration, debayering, stacking, or later image
processing.

The repair implementation is in `indi_allsky/asi676mc.py`; pipeline integration
is in `indi_allsky/processing.py` and `indi_allsky/image.py`.

`IMAGE_ASI676MC_REPAIR.EXCLUDE_ONLY` selects a detection-only alternative while
the main feature remains enabled. A matching bad frame is left byte-for-byte
unchanged, passes through the normal image pipeline, and is saved as the usual
bad JPEG. When that saved image is added to the database, its existing
`exclude` field is set so timelapse and star-trail queries omit it. The gallery
shows the orange **Purple frame excluded** badge when gallery status display is
enabled. Normal frames and frames from other camera models are unaffected.

The default is `true` for new or missing configuration. In addition, the web
settings page selects **Exclude Only** whenever the overall feature transitions
from disabled to enabled. An already-enabled installation retains its explicit
mode, and the operator may deliberately clear the checkbox before saving.
The runtime statuses stored with affected images are `repaired`,
`validation_failed`, and `excluded`; exclude-only mode does not run repair or
post-repair validation and therefore adds only the detector's usual
sub-millisecond overhead.

The feature's master switch is intended only for an ASI676MC that actually
exhibits the purple-frame failure. An unaffected camera should leave the entire
feature disabled. The Image Settings page places that warning directly beside
the master switch; the workflow guidance below is attached to the subordinate
options because it applies only after purple-frame handling has been enabled.

The recommended evidence-collection sequence for an affected camera is:

1. Enable ASI676MC handling and leave **Exclude Only** selected.
2. For minimal disk use, enable **Save Bad and Following RAW FITS**. This works
   in exclude-only mode and retains the untouched purple frame plus its
   immediately following frame. That frame is used only if it passes the
   normal-frame checks.
3. For stronger good/bad/good groups, temporarily enable ordinary FITS saving
   at **Every Image** while Exclude Only remains active. A non-zero periodic
   interval can miss randomly occurring failures.
4. Calibrate and review/apply the derived values, then clear **Exclude Only**
   to activate pixel repair.

Ordinary FITS are written after ASI676MC handling, including when “Save FITS
Pre-Calibration” is selected (that option means pre-dark-calibration). When
actual repair is active, repair-specific diagnostic capture is therefore
needed to preserve the untouched faulty mosaic reliably.

### Test system and evidence package

The Raspberry Pi is the live test system and the only source of untouched
failure captures. Changes on this branch are therefore expected to be fetched
by the Pi, observed in production processing, and either retained or reverted
with a new commit. Do not rewrite or force-push this branch while the highlight
repair is being evaluated; its commit history is the experiment ledger.

Seven bad/following ASI676MC FITS pairs were used for offline comparison. The
two clear-sky fringe pairs are:

| Role | Pair 1 | Pair 2 |
| --- | --- | --- |
| Defective FITS | `fringe_bad_fits_1.fit` | `fringe_bad_fits_2.fit` |
| Following normal FITS | `fringe_ next_fits_1.fit` | `fringe_next_fits_2.fit` |
| Defective raw JPEG | `raw_ccd1_20260730_053431.jpg` | `raw_ccd1_20260730_054552.jpg` |
| Following raw JPEG | `raw_ccd1_20260730_053451.jpg` | `raw_ccd1_20260730_054612.jpg` |
| Defective finished JPEG | `ccd1_20260730_053431.jpg` | `ccd1_20260730_054552.jpg` |
| Following finished JPEG | `ccd1_20260730_053451.jpg` | `ccd1_20260730_054612.jpg` |

The redacted processing configuration is
`indi-allsky_config_id-440_level-20260724-0_20260730_132945.json`. Relevant
daytime settings were MTF stretch with shadows `0.03` and midtones `0.4`,
manual RGB balance `1.28/1.0/0.98`, saturation `1.3`, gamma `1.22`, and
sharpening `0.75`.

The residual magenta error is already measurable in the raw JPEG exported
before stretch, manual white balance, saturation, gamma, and sharpening. Those
later operations make it approximately 15-20 percent more visible, but do not
create it. Below about 240 in the 8-bit raw JPEG, paired repaired and following
frames are effectively color-matched; the remaining error is concentrated in
the brightest transition and clipped regions.

Source green values cannot provide a useful feather signal. Of 120,890 jointly
clipped Bayer cells in clear-sky pair 1, 119,061 already have a minimum source
green value of 65534. Pair 2 has 100,352 such cells out of 101,906. More than
98 percent of the affected cells have therefore lost their green brightness
gradient completely. Transition logic must use the surviving red/blue
relationship rather than the clipped green value.

### Saturated-highlight reconstruction

The camera fault also clips both source green samples before their inverse gain
correction. Without a second reconstruction step, the repaired green planes
plateau below the corrected red and blue planes, leaving saturated highlights
magenta even though unsaturated areas are repaired correctly.

`_pack_clipped_green_masks()` records two compact masks after row-phase
restoration and before applying the gain lookup tables:

- source G1 samples at or above `SOURCE_SATURATION_THRESHOLD`, used by the
  original neighboring-G2 interpolation;
- cells where both source green samples are clipped.

After gain correction and the original G1 interpolation,
`_reconstruct_clipped_green()` handles only the jointly clipped cells. Because
their true green values are no longer recoverable, it raises both corrected
green values from the corrected red and blue in the same Bayer cell. If `high`
and `low` are the larger and smaller of those channels, the Method 3 boundary
estimate is:

```text
base = high - round((high - low)^2 / (2 * high))
```

Method 5, introduced by `71054af0`, retains `base` while `low/high` is at or
below `0.55`, blends toward `high` between `0.55` and `0.75`, and uses `high`
at or above `0.75`. These boundaries are exposed as
`HIGHLIGHT_BLEND_START_RATIO` and `HIGHLIGHT_BLEND_END_RATIO`; `0.55` and
`0.75` remain the defaults. The implementation converts them to equivalent
`base/high` endpoints (the defaults become `719/800` and `775/800`) and uses
an 8-bit fixed-point weight:

```text
scale = 800
start_base = round(scale * (1 - (1 - start_ratio)^2 / 2))
end_base = round(scale * (1 - (1 - end_ratio)^2 / 2))

weight = clamp(
    (scale * base - start_base * high)
        / ((end_base - start_base) * high),
    0,
    1
)
target = round(base + weight * (high - base))
```

This keeps the factor-two behavior at the colored outer boundary, but reaches
the color of the strongest-channel method quickly enough to avoid carrying a
purple deficit across the entire clipped region. The constants are internal
model-specific values that can now be adjusted alongside the measured Bayer
gains. The start ratio must be greater than zero and less than the end ratio;
the end ratio may not exceed one. All recoverable samples and all normal
frames remain untouched.

Across the seven saved FITS pairs, equal-weighted mean transition chroma error
was `0.026618` for factor two, `0.023337` for factor three, `0.028770` for the
maximum-channel method, and `0.020675` for Method 5. These offline values are
comparative diagnostics; visual results from the Pi remain the acceptance
test.

The joint mask is bit-packed and adds 394,272 bytes at the ASI676MC's
3552-by-3552 resolution. Reconstruction remains chunked, and the adaptive
calculation reuses the existing interpolation buffers instead of allocating
another full image plane. The new interpolation also reuses those buffers. On
the Windows analysis system, median full-frame repair time for clear-sky pair 1
changed from approximately 106 ms for factor two to 128 ms for Method 5. It is
only reached after a frame has been classified as bad, so normal-frame
detection cost is unchanged.

### Highlight experiment ledger

The observed results below are part of the implementation history, not a claim
that clipped information can be recovered exactly:

| Method | Commit | Reconstruction | Live observation |
| --- | --- | --- | --- |
| 1 | `d5d75f2b` | Set jointly clipped green to at least `max(red, blue)` | Closest interior color to following normal frames, but a hard cyan onset |
| 2 | `02e321ec` | Set jointly clipped green to at least the red/blue mean | Smooth natural-color onset, but a broad purple band with a visible bright-side edge |
| 3 | `ca835c21` | Adaptive factor-two estimate | Narrower purple band; both band edges remained visible |
| 4 | `5a6e3ab0` | Adaptive factor-three estimate | Smooth transition, but a purple tinge extended across most of the clipped region |
| 3 restored | `c848d2fc` | Revert Method 4 | Returned the Pi to the factor-two baseline for paired testing |
| 5 | `71054af0` | Factor two at the boundary, bounded blend to maximum | Live Pi result accepted: smooth transitions, white clipping, and only a barely detectable residual tint |

To return from Method 5 to the immediately preceding factor-two implementation
with a new commit:

```text
git revert 71054af0
```

After that revert, the older experiments can be restored with new commits:

```text
# Restore Method 4 (factor three)
git revert c848d2fc

# Or restore Method 2 from the factor-two baseline
git revert ca835c21

# Restore Method 1 after reverting Method 3
git revert 02e321ec
```

Run only the path needed, in order, and inspect the staged patch before
continuing if Git reports a conflict. Do not combine these with `git reset` or
force-push the shared test branch. A dirty Pi worktree must first be committed
or stashed before a revert or rebase can proceed.

### Diagnostic FITS pair capture

Commit `4e553308` added the independently selectable
`IMAGE_ASI676MC_REPAIR.SAVE_DIAGNOSTIC_FITS` option. When enabled:

1. A frame classified as `repaired`, `validation_failed`, or `excluded` causes
   the untouched incoming FITS file to be copied before the source is removed.
2. The immediately following successfully ingested frame for the same camera is
   copied as the comparison FITS.
3. Consecutive bad frames share one physical file where appropriate: a frame
   can be both the `following` member of one pair and the `bad` member of the
   next pair.
4. Copying and database/upload failures are logged and isolated so diagnostic
   capture cannot stop the normal image pipeline.

Pair state is held in `ImageWorker.asi676mc_diagnostic_pending`, keyed by camera
ID. A service restart between the bad frame and its successor can therefore
leave a pair with only its bad member.

The copies are standard `IndiAllSkyDbFitsImageTable` assets. Existing FITS
expiration, local URL, file-transfer, and S3 behavior applies. No database
migration was added.

The FITS row JSON uses this shape:

```json
{
  "asi676mc_diagnostic": {
    "version": 1,
    "source": "untouched_input",
    "roles": [
      {
        "capture_id": "<pair UUID>",
        "role": "bad"
      }
    ]
  }
}
```

The associated rendered image row stores a small
`asi676mc_diagnostic_fits` JSON object containing the FITS row ID and the same
role list. Pair UUIDs, rather than timestamps, associate the bad and following
files.

Downloads appear as `Bad FITS` and `Next FITS` in the standard Image Viewer
download strip. The gallery deliberately exposes no diagnostic FITS controls
or URLs, including in its enlarged PhotoSwipe view, so its toolbar cannot cover
the timestamp or other image annotations.

### Repair and calibration utility

`misc/asi676mc_frame_repair.py` is the publishable, self-contained companion
to the live feature. It depends only on NumPy and Astropy and contains the same
Method 5 repair mathematics as `indi_allsky/asi676mc.py`. Every adjustable
detection, gain, saturation, highlight, and calibration constant is grouped at
the top of the file.

The original single-file workflow remains available:

```text
# Classify without writing anything
python misc/asi676mc_frame_repair.py bad.fit --check-only

# Write bad_corrected.fit only when the failure is detected
python misc/asi676mc_frame_repair.py bad.fit
```

Folder calibration is explicit:

```text
python misc/asi676mc_frame_repair.py /path/to/fits --calibrate
```

It recursively inspects RAW16 RGGB FITS files, classifies each from its own
pixels, and matches every bad frame to the closest normal frame before and/or
after it. A match must have the same dimensions, Bayer pattern, exposure,
gain, binning, and compatible camera identity, and must fall within 90 seconds
by default. Filenames are not used for classification or pairing when the FITS
timestamp is available.

Calibration refuses to produce settings unless all of these conditions hold:

- at least seven independently detected bad frames have compatible matches;
- every detected bad frame has at least one matched normal frame;
- distinct matched normal frames provide a minimum normal/bad ratio of `1:1`;
- at least two exposure levels are represented;
- normal and failed signatures are cleanly separated by the detector;
- sufficient stable, jointly clipped daylight highlight samples are present;
- no conflicting explicit camera identity is found.

A normal capture on both sides of every failure gives the preferred `2:1`
ratio. The tool reports a warning, but does not fail, when only the required
`1:1` evidence is available.

The four Bayer gains are measured from stable, unsaturated sparse samples after
accounting for the one-row displacement. Before/after references are
interpolated to the failure timestamp. The source-green ceiling is measured
separately. Highlight start/end ratios are grid-searched using chromaticity
error rather than absolute brightness; fully clipped normal references are
excluded because they contain no target color. A neighboring grid result must
improve the proven `0.55/0.75` score by more than two percent before replacing
those defaults.

Finally, the rounded recommendations are applied in memory to every matched
bad FITS and every distinct matched normal FITS. Calibration fails if a bad
repair retains the signature, a normal frame is classified as bad, or any
normal-frame data changes.

The numerical calibration engine produces
`asi676mc_calibration_report.txt`. Its first section is headed
`REVIEW THESE CALIBRATION VALUES` and uses the exact field labels shown under
**Configuration > Image > ASI676MC RAW16 Frame Repair**. The web integration
also stores those seven values in its compact result so they can be reviewed
beside the current configuration and, by an administrator, applied through
indi-allsky's normal settings workflow.

The report continues with human-readable evidence, stability, signature, and
highlight-fit details for auditing. The numerical engine itself never edits the
live indi-allsky configuration and never overwrites source FITS; authenticated
web views own the optional configuration save and source cleanup workflows.

Against the complete saved development collection, the tool found 14 matched
bad frames and 21 distinct normal references across 14 exposure levels. Seven
failures had both a preceding and following reference. It reproduced the
accepted `0.55/0.75` highlight boundaries after overfit protection, measured a
source-green plateau of `65534`, and estimated gains within roughly one percent
of the live defaults.

### Authenticated web calibration tool

When ASI676MC frame handling is enabled, the **Tools > ASI676MC Calibration**
entry is shown to logged-in users. It is hidden when the repair master switch is
off so installations that do not use this camera-specific feature have no extra
Tools-menu clutter. The page itself exposes the folder-calibration workflow
without requiring shell access and retains its intentionally stricter access
rule: a real authenticated user is required even when the installation has
globally disabled login checks. Uploaded RAW FITS may contain camera, time, and
location metadata and are never published under the web image directory.

The operator selects the complete collection in one browser file-picker action.
JavaScript then transfers the selected files sequentially into a private,
randomly named session. This is an implementation detail rather than a manual
one-file-at-a-time workflow: it provides per-file progress and avoids sending a
several-hundred-megabyte multipart request. A visible **Cancel upload** action
aborts the current browser transfer, tombstones the server session against a
concurrent upload request, and immediately deletes every FITS already received
for that run. Additional upload safeguards are:

- only uncompressed `.fit`, `.fits`, and `.fts` names are accepted;
- the mandatory first FITS `SIMPLE` card is checked before admission;
- Astropy and the calibration engine perform full structural and RAW16 RGGB
  validation in the background job;
- sessions are owned by the authenticated username and use unguessable IDs;
- file count, individual size, and total-session size are bounded; and
- every session, including an interrupted partial upload, expires after seven
  days.

The setup page follows indi-allsky's dark-card interface: reference matching is
shown once because it applies to both evidence sources, while saved FITS
discovery and manual upload use matching source cards. The cards sit side by
side on wide displays and stack on narrow ones. Result actions wrap in a stable
order on small screens, and the values table scrolls horizontally instead of
compressing long configuration labels. **Current FITS capture settings** shows
the effective state of every relevant switch and resolves the combination into
one state-specific, action-oriented message instead of stacking overlapping
notices. It also makes clear that these settings concern future captures;
existing suitable FITS can still be searched or uploaded. Informational and
warning text uses dark high-contrast callouts with semantic edge colors.
The shared **Maximum separation** value is validated before either a saved FITS
search or a manual upload begins, then checked again by the server; an invalid
value therefore cannot waste a large upload or broaden matching silently.

The capture message covers the settings matrix as follows:

| Purple-frame mode | Bad + following RAW FITS | Ordinary FITS | Message and action |
| --- | --- | --- | --- |
| Off | Either (the option is inactive) | Every Image | Complete uncompressed sequences can be uploaded manually; compressed files must be decompressed first. New purple frames are not flagged for automatic search. Enable handling in Exclude Only mode for automatic discovery. |
| Off | Either | Off, periodic, or invalid | Future collection is not dependable. Enable Exclude Only, then use Bad + following RAW FITS for low disk use or Every Image for complete sequences. |
| Exclude Only | On | Every Image | Untouched full sequences are collected. Diagnostic FITS save each purple frame unchanged and the immediately following frame; ordinary FITS can add normal references on either side. |
| Exclude Only | On | Off or periodic | Low-disk collection is ready. The immediately following frame is used only when compatible; periodic ordinary FITS is optional. |
| Exclude Only | On | Invalid interval | Diagnostic FITS remain the low-disk calibration source. Correct the malformed ordinary FITS interval or turn ordinary saving off. |
| Exclude Only | Off | Every Image | Untouched complete sequences are collected and can provide good/bad/good groups. |
| Exclude Only | Off | Periodic | The interval may miss a random purple frame. Enable diagnostic FITS or use Every Image. |
| Exclude Only | Off | Off or invalid | No reliable calibration FITS will be saved. Enable diagnostic FITS or correct ordinary saving and use Every Image. |
| Repair active | On | Every Image | The diagnostic purple frame remains untouched and full-rate ordinary FITS can add reference candidates; this uses the most disk. |
| Repair active | On | Off or periodic | Low-disk pre-repair diagnostic collection is ready; periodic ordinary FITS is optional. |
| Repair active | On | Invalid interval | Diagnostic FITS remain the pre-repair calibration source. Correct the malformed ordinary FITS interval or turn ordinary saving off. |
| Repair active | Off | Any | Ordinary FITS are post-repair and cannot be relied on as the original bad mosaic. Enable diagnostic FITS, or switch to Exclude Only and use Every Image. |

An invalid or sub-one-day retention value adds one warning that automatic
saved FITS search is unavailable while manual upload remains usable. FITS
compression is displayed as inactive when ordinary FITS saving is off.
Automatic saved FITS search reads indi-allsky's compressed FITS directly;
manual upload accepts only uncompressed FITS, so `.fit.gz`, `.fits.gz`, and
`.fts.gz` files must be decompressed before selection.

The same page can instead select **Find saved FITS and calibrate**. The operator
chooses a maximum of 7-100 purple-frame groups; this is a purple-frame count,
not a raw file count, because the selector automatically includes up to two
adjacent normal reference FITS for each purple frame. The default is 25 groups.
Discovery is camera-specific and works newest first. It stops when the requested
number of usable groups has been selected or when no older eligible record
remains inside `IMAGE_FITS_EXPIRE_DAYS`. The cutoff follows indi-allsky's own
`dayDate` expiration rule, including the whole oldest retained day.

Two database evidence sources are combined:

- repair-specific diagnostic FITS carry explicit `bad` and `following` capture
  roles and are preferred because the bad source is guaranteed untouched; the
  following candidate must still pass the normal-frame checks;
- ordinary FITS are aligned by exposure time, exposure, and gain to image rows
  marked `excluded`, then the nearest compatible ordinary FITS before and/or
  after are selected as normal references.

An ordinary FITS corresponding to a frame marked `repaired` or
`validation_failed` is excluded as both a bad source and a normal reference,
because the stored mosaic may already have been changed. Known bad captures,
missing local files, unsupported assets, and candidates without an adjacent
normal FITS are ignored. Database rows that point only to remote/S3 assets are
reported as unavailable; discovery never downloads them. Both uncompressed
FITS and the `.fit.gz`/`.fits.gz` forms written by indi-allsky are accepted,
using Astropy directly without another FITS program.

If fewer groups exist than requested, calibration still runs with every usable
group found as long as at least seven purple frames and seven distinct normal
references remain. Otherwise the page reports the specific shortfall and the
next useful action instead of queueing a job: enable flagging when no saved
frame is marked bad, collect compatible adjacent references when flagged bad
FITS are unmatched, widen the separation only when appropriate, or upload an
existing collection. The result-status banner states success, source cleanup,
that only the seven derived values are in scope, and whether applying the result
would materially change the current values.
The structured **Evidence used** section carries the counts. The downloadable
text report appends the full database-selection audit, including the requested
limit, retention cutoff, and missing-local-file count.

The default session directory is Flask's non-public `instance` directory and
may be overridden with `ASI676MC_CALIBRATION_FOLDER`. Do not move sessions into
`/tmp`: the capture service uses systemd `PrivateTmp`, so gunicorn and the video
worker may see different temporary directories. Do not put sessions inside the
public image tree either.

After upload, a priority-200 job runs in the existing video worker so Astropy
loading, sparse fitting, and full-resolution validation cannot hold a gunicorn
request open. Normal manually generated videos use priority 100 and therefore
remain ahead of calibration. The browser stores the current session ID locally
and resumes status polling after a page reload.

Saved database FITS are staged into the same private session with hard links,
which preserve the selected inode without copying gigabytes or modifying the
database-owned path. A cross-filesystem installation falls back to symbolic
links. Session cleanup removes only those private links; it never deletes the
original database FITS. The existing background engine and validation policy
are therefore identical for uploaded and discovered evidence.

The web evidence policy ignores and reports unmatched purple frames, then
continues only if at least seven matched failures and every other evidence
check passes. Unused normal frames and structurally rejected files are also
reported rather than silently treated as evidence.

Uploaded source FITS are deleted before the worker publishes either a successful
or failed final status. Consequently, a result visible in the browser guarantees
that its source uploads are no longer retained. The small manifest, result,
report, and audit log remain for up to seven days.

Before a manual transfer starts, the browser checks the same 200-file,
256-MiB-per-file, and 2-GiB-per-run limits enforced by the streaming upload
endpoint. An impossible selection therefore fails immediately instead of after
most of a large transfer; the server repeats every check for security.

Interrupted uploads do not depend on the browser returning to the page for
eventual cleanup. Calibration sessions are private scratch data and have no FITS
database row, so normal database-backed FITS expiry cannot identify them. The
regular indi-allsky asset-expiration job now runs the calibration session's
fixed seven-day cleanup alongside its ordinary work. Since that job normally
runs at day/night transitions, an abandoned partial upload is removed on the
first regular expiration pass after it becomes seven days old. Starting a new
calibration session also performs the same cleanup immediately.

On success, the page switches to a results-only view showing the seven
camera-specific values actually derived by calibration: four Bayer gains,
source saturation threshold, and two highlight blend boundaries. Each row also
shows the normalized value from the currently loaded configuration, so the
operator can review the change before applying it. The current values are read
when result status is requested rather than stored with the result, keeping a
retained result accurate after settings change elsewhere. Detection thresholds,
sample step, chunk size, and operational switches are validated/current values
rather than measurements and are not presented as derived. The complete
human-readable report is available through an owner-checked download route.
Returning to the page restores that result without restoring the browser's file
selection. **Reset / recalibrate** deletes the retained result/report session
and returns the page to its original file-selection state. In the result action
row, this reset button is immediately left of **Download text report** so the
controls remain orderly when the header wraps on a narrow display. An
incomplete upload cannot be resumed after navigation, so it is cancelled and
removed when the page is revisited.
If upload cancellation cannot be confirmed, the page retains the session ID and
shows **Retry cancellation** instead of hiding the only cleanup action. The
cancel endpoint is idempotent, so a retry is safe when the first request reached
the server but its response was lost.

Administrators can choose **Apply values and reload** after a successful run.
The result is compared with the currently loaded seven measured settings. An
exact match or a difference below deliberately narrow per-field tolerances is
shown as an emphasized line in the shared result-status banner, because
applying an effectively equivalent result is unlikely to change repaired
pixels noticeably. A material difference asks the operator to review both
columns; an unavailable comparison says so explicitly. Apply/reload and reset
feedback replaces the content of that same banner instead of creating another
notice. Non-fatal observations are combined by category in one **Calibration
notes** callout below the evidence counts: search shortfall, one-sided reference
coverage, and skipped/unusable files each appear at most once.
Known apply rejections carry small response codes so the browser can show the
specific configuration-change or expired-result guidance without wrapping it
in a second, repetitive error. A rejected reset says the result remains; a
network or unreadable response instead asks the operator to reload because the
browser cannot know whether server-side deletion completed.
The action verifies that the active configuration is still the same version
used when calibration started, writes only the seven measured values through
indi-allsky's normal versioned configuration save path, and queues a normal
configuration reload. Operational choices such as enabling repair and saving
diagnostic FITS are preserved and are never switched on automatically. A
configuration change made while calibration was running blocks application and
asks the administrator to review the change and calibrate again.

Calibration-engine failures are translated into first-time-user guidance for
the common cases: incompatible RAW data, fewer than seven matched groups, too
few distinct normal references, only one exposure level, mixed cameras,
overlapping normal/bad signatures, insufficient bright highlights, or final
safety-check failure. The failure message confirms that no settings changed
and whether uploads or temporary database links were removed. Unexpected
internal details remain in the log rather than exposing paths in the browser.

The page checks for multi-file selection, Fetch, FormData, Promises, async
JavaScript, upload cancellation, and writable local browser storage before
allowing a run. A specific warning replaces silent failure when any required
browser feature is missing or blocked; a separate message covers JavaScript
being disabled entirely.

## Files involved in diagnostic capture

- `indi_allsky/asi676mc.py`
  - `DIAGNOSTIC_METADATA_KEY`
  - `DIAGNOSTIC_BAD_STATUSES`
  - `diagnostic_capture_plan()`
- `indi_allsky/image.py`
  - per-camera pending-pair state
  - call immediately after `correct_asi676mc_frame()`
  - `capture_asi676mc_diagnostic_fits()`
  - `_archive_asi676mc_diagnostic_fits()`
  - image-row diagnostic metadata
- `indi_allsky/config.py`
  - default for `SAVE_DIAGNOSTIC_FITS`
- `indi_allsky/flask/forms.py`
  - settings field
  - saved FITS purple-group limit
  - diagnostic FITS lookup/pairing
  - Image Viewer JSON fields
  - labels in the standard FITS viewer
- `indi_allsky/flask/views.py`
  - settings load/save wiring
  - camera-gated Image Viewer and gallery wiring
  - authenticated calibration session, status, report, discard, and apply routes
  - retention-bounded local FITS discovery and background-job queueing
- `indi_allsky/flask/templates/config.html`
  - switch, help text, submission list, and master-switch grouping
- `indi_allsky/asi676mc_calibration.py`
  - private upload-session lifecycle, bounds, result/config comparison,
    retention, and report ownership
  - newest-first diagnostic/ordinary FITS selection and zero-copy staging
- `indi_allsky/video.py`
  - low-priority background calibration action
  - regular catch-all expiration for abandoned calibration sessions
- `indi_allsky/flask/templates/asi676mc_calibration.html`
  - browser capability checks, multi-select upload, cancellation, progress,
    saved FITS controls, retained results, configuration-match hints, and report
    download
- `indi_allsky/flask/base_views.py` and `indi_allsky/flask/templates/base.html`
  - repair-enabled Tools-menu visibility flag and conditional menu entry
- `indi_allsky/flask/templates/imageviewer.html`
  - `Bad FITS` and `Next FITS` controls
- `indi_allsky/flask/templates/gallery.html`
  - repair outlines, badges, tooltips, and repaired-only filtering
- `testing/image/test_asi676mc_repair.py`
  - bad/following and consecutive-bad pairing tests

## Removing only diagnostic FITS capture

This is the preferred removal scope if frame correction itself is still useful.

1. Remove `SAVE_DIAGNOSTIC_FITS` from the default configuration, settings form,
   settings template, and settings load/save code.
2. Remove the diagnostic constants and `diagnostic_capture_plan()` from
   `indi_allsky/asi676mc.py`.
3. From `ImageWorker`, remove the pending-pair dictionary, the guarded
   `capture_asi676mc_diagnostic_fits()` call, both diagnostic capture methods,
   and persistence of `asi676mc_diagnostic_fits` into image metadata.
4. Remove `_asi676mc_diagnostic_assets()` and its Image Viewer response fields
   from `indi_allsky/flask/forms.py`. Remove the diagnostic labels from the FITS
   viewer. The camera-specific filter added to the ordinary same-timestamp FITS
   lookup is safe to retain.
5. Remove the Image Viewer diagnostic spans and JavaScript.
6. Remove the diagnostic pairing tests, but retain all detection, repair,
   validation, timing, and memory tests.
7. Run the ASI676MC unit tests and JavaScript syntax checks for the config,
   gallery, and Image Viewer templates.

Removing this code needs no database migration. Existing diagnostic FITS remain
valid ordinary FITS records and will expire according to
`IMAGE_FITS_EXPIRE_DAYS`. Existing image/FITS JSON keys are harmless if left in
the database. Prefer normal expiration over manually deleting files and rows.

## Removing the complete ASI676MC feature

If the camera issue is fixed upstream or this customization is no longer
wanted, first follow the diagnostic-removal steps above, then:

1. Remove `indi_allsky/asi676mc.py` and its test module.
2. Remove `misc/asi676mc_frame_repair.py` and
   `testing/image/test_asi676mc_calibration_tool.py` if the command-line detector,
   repairer, and calibration workflow is no longer wanted.
3. Remove the ASI676MC result property from the processing image-reference
   object.
4. Remove `correct_asi676mc_frame()`, its helper, and the early pipeline call.
5. Remove the complete `IMAGE_ASI676MC_REPAIR` configuration block and all
   corresponding form validators, fields, view wiring, camera-support checks,
   and Image-tab controls.
6. Remove repair metadata persistence and all gallery repair status, outline,
   badge, tooltip, and filter code.
7. Search the tree for both `asi676mc` and `IMAGE_ASI676MC_REPAIR`; no runtime
   references should remain.
8. Compare the final result against the commit series above and run the
   relevant image and web-template checks.

Stored JSON audit data does not require cleanup when the complete feature is
removed.

## Removing only saturated-highlight reconstruction

To retain the original row-phase and gain repair but remove the later
highlight refinement:

1. Replace the runtime call to `_pack_clipped_green_masks()` with
   `_pack_clipped_green_mask()` and keep only `green1_clipped_packed`.
2. Remove `both_green_clipped_packed` from `_reconstruct_clipped_green()` and
   delete the block beginning with its `numpy.unpackbits()` call.
3. Remove `_pack_clipped_green_masks()`, restoring the original single-mask
   implementation inside `_pack_clipped_green_mask()`.
4. Remove the `_HIGHLIGHT_BLEND_*` constants.
5. Remove the jointly-clipped-green and bounded-transition unit tests and the
   joint-mask assertions from the partial-byte test.

This narrower removal does not affect configuration, database rows, gallery
metadata, or diagnostic FITS capture.
