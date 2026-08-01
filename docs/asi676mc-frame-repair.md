# ASI676MC frame repair and diagnostic FITS

This document records the custom ASI676MC feature carried by
`dev/asi676mc-image-correction`. It is intended to give a future maintainer—or
another Codex chat—enough context to modify or remove the feature without
disturbing the rest of the indi-allsky pipeline.

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

The default is `false`, so existing installations continue to repair detected
frames. The runtime statuses stored with affected images are `repaired`,
`validation_failed`, and `excluded`; exclude-only mode does not run repair or
post-repair validation and therefore adds only the detector's usual
sub-millisecond overhead.

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

### Standalone repair and calibration tool

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

The only calibration output is `asi676mc_calibration_report.txt`. Its first
section is headed `TYPE THESE VALUES INTO YOUR CONFIG` and uses the exact field
labels shown under **Configuration > Image > ASI676MC RAW16 Frame Repair**.
Values must be typed into that normal settings form and reviewed before repair
is enabled. The standalone tool neither reads nor writes installation
configuration files; its only calibration output is the text report.

The report continues with human-readable evidence, stability, signature, and
highlight-fit details for auditing. The tool never edits the live indi-allsky
configuration and never overwrites source FITS. An existing report also
requires `--overwrite`.

Against the complete saved development collection, the tool found 14 matched
bad frames and 21 distinct normal references across 14 exposure levels. Seven
failures had both a preceding and following reference. It reproduced the
accepted `0.55/0.75` highlight boundaries after overfit protection, measured a
source-green plateau of `65534`, and estimated gains within roughly one percent
of the live defaults.

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
  - diagnostic FITS lookup/pairing
  - Image Viewer JSON fields
  - labels in the standard FITS viewer
- `indi_allsky/flask/views.py`
  - settings load/save wiring
  - camera-gated Image Viewer and gallery wiring
- `indi_allsky/flask/templates/config.html`
  - switch, help text, submission list, and master-switch grouping
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
   `testing/image/test_asi676mc_standalone.py` if the standalone detector,
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
