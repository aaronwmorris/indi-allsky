# Order of Operations
1. Start image pre-save hook (runs concurrently in background)
1. Dark frame calibration
1. Save FITS
1. Calculate jSQM
1. Debayer
1. Calculate ADU
1. Stack
1. Save RAW (non-stacked)
1. Stretch (16-bit)
1. 16-bit Contrast enhance (CLAHE)
1. Downsample to 8-bit
1. Detect stars
1. Line detection
1. Draw detections
1. Rotate
    1. 90 degree
    1. Angle
1. Flip verticle
1. Flip hoizontal
1. Crop
    *  Image Circle or ROI
1. White balance
    1. SCNR
    1. MTF WB
    1. Manual WB
    1. Auto WB
1. Saturation
1. Gamma Correction
1. Sharpen
1. Contrast enhance (CLAHE)
1. Colorize (if grayscale)
1. Extract Long Term Keogram data
1. Image Circle Mask
1. Realtime Keogram
1. Fish-eye to Panorama
    1. Flip
    1. Label
    1. Save panorama image
1. Generate image for circular display
1. Logo overlay
1. Scale image
1. Image border
1. Overlays
    1. Moon overlay
    1. Lightgraph overlay
    1. Remote Image overlay
1. Label image
    1. Orbs
    1. Cardinal Directions
    1. Wait on pre-save hook to complete
    1. Text Overlay
1. Save image
1. Execute image post-save hook


# History
## Feb 2026
* Add remote image overlay
* Add sharpen

## Jan 2026
* Add MTF WB

## Oct 2025
* Add Image Circle Mask crop

## Jun 2025
* Add pre- and post-save hooks

## Mar 2025
* Add Gamma Correction
* Realtime Keogram

## Jan 2025
* Add Lightgraph Overlay

## Dec 2024
* Perform debayer before stacking

## Nov 2024
* Add Image border
* Add Moon Overlay
* Fish-eye to Panorama before Logo overlay and Scale image

## Nov 2023
* Add cardinal directions

## Oct 2023
* Moved star and line detection before rotation/flip/crop