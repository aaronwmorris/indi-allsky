#!/usr/bin/env python3

# Reproduces https://github.com/aaronwmorris/indi-allsky/issues/2965
#
# getChartData() in indi_allsky/flask/views.py replaces the correctly-shaped
# default mask with the loaded detection mask via `numpy_mask = _sqm_mask == 0`
# without checking that the detection mask's dimensions actually match the
# current image. If a user's saved detection mask has different dimensions
# than the current capture (different resolution/binning), numpy.ma.masked_array
# raises numpy.ma.core.MaskError and the chart endpoint returns HTTP 500 for
# every request.
#
# This isolates just the masking logic (no Flask app, DB, or camera needed)
# and checks it against both the old (buggy) and new (fixed) behavior.

import sys
import numpy


def apply_mask_old(image_data, sqm_mask):
    if sqm_mask is None:
        numpy_mask = numpy.full(image_data.shape[:2], True, numpy.bool_)
    else:
        numpy_mask = sqm_mask == 0

    return numpy.ma.masked_array(image_data[:, :, 0], mask=numpy_mask)


def apply_mask_fixed(image_data, sqm_mask):
    if sqm_mask is not None and sqm_mask.shape != image_data.shape[:2]:
        sqm_mask = None

    if sqm_mask is None:
        numpy_mask = numpy.full(image_data.shape[:2], True, numpy.bool_)
    else:
        numpy_mask = sqm_mask == 0

    return numpy.ma.masked_array(image_data[:, :, 0], mask=numpy_mask)


def main():
    # image is 1000x600 (matches a real capture)
    image_data = numpy.zeros((600, 1000, 3), numpy.uint8)

    # detection mask was saved at a different resolution (800x500) -- the
    # exact class of mismatch reported in #2965 (data size 5649400 vs mask
    # size 6528000, i.e. two arrays of different pixel counts)
    mismatched_mask = numpy.zeros((500, 800), numpy.uint8)

    old_crashed = False
    try:
        apply_mask_old(image_data, mismatched_mask)
    except numpy.ma.core.MaskError:
        old_crashed = True

    if not old_crashed:
        print('FAIL: expected old behavior to raise MaskError on shape mismatch')
        sys.exit(1)

    print('OK: confirmed the bug reproduces on the old code path (MaskError)')

    try:
        result = apply_mask_fixed(image_data, mismatched_mask)
    except numpy.ma.core.MaskError:
        print('FAIL: fixed code path still raises MaskError on shape mismatch')
        sys.exit(1)

    assert result.shape == image_data.shape[:2], 'result should fall back to full image shape'
    print('OK: fixed code path falls back gracefully instead of crashing')

    # sanity check: matching shapes still mask correctly (unaffected by the fix)
    matching_mask = numpy.zeros((600, 1000), numpy.uint8)
    matching_mask[0:100, 0:100] = 255
    result = apply_mask_fixed(image_data, matching_mask)
    assert result.mask[50, 50] == False and result.mask[500, 500] == True, \
        'matching-shape mask should still be applied normally'
    print('OK: matching-shape mask still applies normally (no regression)')


if __name__ == '__main__':
    main()
