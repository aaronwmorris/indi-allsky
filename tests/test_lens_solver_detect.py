import cv2
import numpy

from indi_allsky import lens_solver
from indi_allsky.lens_solver import detection
from indi_allsky.lens_solver import IndiAllSkyLensSolver


def make_starfield(positions, shape=(600, 800), radius=2, seed=42):
    img = numpy.full(shape, 12, dtype=numpy.uint8)   # sky background
    noise = numpy.random.RandomState(seed).normal(0, 2, shape)
    img = numpy.clip(img + noise, 0, 255).astype(numpy.uint8)
    for x, y in positions:
        cv2.circle(img, (int(x), int(y)), radius, 230, -1)
    return cv2.GaussianBlur(img, (5, 5), 1.2)


def test_detects_synthetic_stars_within_one_pixel():
    positions = [(100, 100), (400, 300), (700, 500), (250, 450), (600, 80)]
    img = make_starfield(positions)
    solver = IndiAllSkyLensSolver({})
    det = solver.detectStars(img)
    assert det.shape[0] >= 5
    for x, y in positions:
        d = numpy.hypot(det[:, 0] - x, det[:, 1] - y).min()
        assert d < 1.5


def test_detect_mask_excludes_region(tmp_path):
    positions = [(100, 100), (700, 500)]
    img = make_starfield(positions)

    mask = numpy.full((600, 800), 255, dtype=numpy.uint8)
    mask[50:150, 50:150] = 0                # blacks out star at (100,100)
    mask_file = tmp_path / 'mask.png'
    cv2.imwrite(str(mask_file), mask)

    solver = IndiAllSkyLensSolver({'DETECT_MASK': str(mask_file)})
    det = solver.detectStars(img)
    assert numpy.hypot(det[:, 0] - 100, det[:, 1] - 100).min() > 20
    assert numpy.hypot(det[:, 0] - 700, det[:, 1] - 500).min() < 1.5


def test_detection_count_bounded():
    # bound the top end too, not just ">= 5", so unbounded detection counts can't slip through
    positions = [(100, 100), (400, 300), (700, 500), (250, 450), (600, 80)]
    img = make_starfield(positions)
    solver = IndiAllSkyLensSolver({})
    det = solver.detectStars(img)
    assert 5 <= det.shape[0] <= 12


def test_detections_sorted_by_flux_desc():
    # not asserted elsewhere; MAX_DETECTED_STARS truncation (brightest N) depends on it
    img = numpy.full((600, 800), 12, dtype=numpy.uint8)
    noise = numpy.random.RandomState(3).normal(0, 2, (600, 800))
    img = numpy.clip(img + noise, 0, 255).astype(numpy.uint8)
    cv2.circle(img, (200, 200), 4, 250, -1)    # bright, large
    cv2.circle(img, (600, 400), 1, 60, -1)     # faint, small
    img = cv2.GaussianBlur(img, (5, 5), 1.2)

    solver = IndiAllSkyLensSolver({})
    det = solver.detectStars(img)
    assert det.shape[0] >= 2
    assert numpy.all(numpy.diff(det[:, 2]) <= 0)

    bright_idx = numpy.argmin(numpy.hypot(det[:, 0] - 200, det[:, 1] - 200))
    faint_idx = numpy.argmin(numpy.hypot(det[:, 0] - 600, det[:, 1] - 400))
    assert det[bright_idx, 2] > det[faint_idx, 2]


def test_empty_and_degenerate_images(monkeypatch):
    # must return shape (0, 3) float64 (callers index [:, :2]), never raise, never shape (0,)
    solver = IndiAllSkyLensSolver({})

    for image in (
        numpy.zeros((200, 300), dtype=numpy.uint8),          # all-black
        numpy.full((200, 300), 255, dtype=numpy.uint8),      # all-saturated
        numpy.full((200, 300), 30, dtype=numpy.uint8),       # flat, no stars
    ):
        det = solver.detectStars(image)
        assert det.shape == (0, 3)
        assert det.dtype == numpy.float64

    assert solver.buildExclusionMask((200, 300)) is None    # no config -- no exclusions

    # a component-count flood is a structured empty result, not an attempt to process 5000+ blobs
    positions = [(100, 100), (400, 300), (700, 500), (250, 450), (600, 80)]
    starfield = make_starfield(positions)
    monkeypatch.setattr(detection, 'MAX_COMPONENTS', 2)
    det = solver.detectStars(starfield)
    assert det.shape == (0, 3)
    assert det.dtype == numpy.float64


def test_mask_binarized_and_resized_correctly(tmp_path):
    # mask at a different resolution with an anti-aliased edge; fails against a
    # binarize-before-resize (or never-binarize) implementation
    real_star = (700, 500)
    excluded_star = (162, 100)     # lands in the mask's gray transition band
    img = make_starfield([excluded_star, real_star])

    small_mask = numpy.full((300, 400), 255, dtype=numpy.uint8)
    small_mask[20:80, 20:80] = 0
    small_mask[20:80, 80:84] = 90          # explicit gray band, < 127
    mask_file = tmp_path / 'mask.png'
    cv2.imwrite(str(mask_file), small_mask)

    solver = IndiAllSkyLensSolver({'DETECT_MASK': str(mask_file)})
    det = solver.detectStars(img)

    assert numpy.hypot(det[:, 0] - excluded_star[0], det[:, 1] - excluded_star[1]).min() > 20
    assert numpy.hypot(det[:, 0] - real_star[0], det[:, 1] - real_star[1]).min() < 1.5


def test_mask_follows_image_flip(tmp_path):
    # masks are authored in sensor orientation; with IMAGE_FLIP_V set, the
    # mask must be flipped the same way the captured frames were
    real_star = (700, 500)
    excluded_star = (100, 100)
    img = make_starfield([excluded_star, real_star])

    # authored mask excludes the BOTTOM-left corner; after flip_v it
    # covers the top-left corner where excluded_star sits
    mask = numpy.full((600, 800), 255, dtype=numpy.uint8)
    mask[400:600, 0:200] = 0
    mask_file = tmp_path / 'mask.png'
    cv2.imwrite(str(mask_file), mask)

    solver = IndiAllSkyLensSolver({'DETECT_MASK': str(mask_file), 'IMAGE_FLIP_V': True})
    det = solver.detectStars(img)

    assert numpy.hypot(det[:, 0] - excluded_star[0], det[:, 1] - excluded_star[1]).min() > 20
    assert numpy.hypot(det[:, 0] - real_star[0], det[:, 1] - real_star[1]).min() < 1.5


def test_orb_band_masks_all_four_edges():
    # orbs at all four borders; none reported. text-label masking is out of scope here
    # (covered by test_detect_mask_excludes_region / test_mask_binarized_and_resized_correctly)
    real_star = (400, 300)
    img = make_starfield([real_star])
    cv2.circle(img, (5, 300), 4, 255, -1)      # left edge
    cv2.circle(img, (795, 300), 4, 255, -1)    # right edge
    cv2.circle(img, (400, 5), 4, 255, -1)      # top edge
    cv2.circle(img, (400, 595), 4, 255, -1)    # bottom edge

    config = {'ORB_PROPERTIES': {'MODE': 'ha', 'RADIUS': 9}}
    solver = IndiAllSkyLensSolver(config)
    det = solver.detectStars(img)

    assert numpy.hypot(det[:, 0] - 400, det[:, 1] - 300).min() < 1.5
    assert numpy.all(det[:, 0] > 20)
    assert numpy.all(det[:, 0] < 780)
    assert numpy.all(det[:, 1] > 20)
    assert numpy.all(det[:, 1] < 580)


def test_star_detected_across_psf_radii():
    # sweeps PSF radius so a regression reintroducing an upper area cap (which
    # previously discarded real stars past a few pixels) is caught directly
    for radius in (2, 4, 6, 8):
        img = make_starfield([(400, 300)], radius=radius, seed=11)
        solver = IndiAllSkyLensSolver({})
        det = solver.detectStars(img)
        assert det.shape[0] >= 1, 'PSF radius {0}px was rejected'.format(radius)
        assert numpy.hypot(det[:, 0] - 400, det[:, 1] - 300).min() < 2.0


def test_large_blob_does_not_suppress_real_stars():
    # deliberately no upper area cap (see MIN_COMPONENT_AREA's comment); a cloud-sized
    # component must not crash detection, suppress the real star, or fragment into many false ones
    real_star = (700, 500)
    img = make_starfield([real_star])
    cv2.circle(img, (150, 150), 13, 240, -1)   # ~530px filled disk

    solver = IndiAllSkyLensSolver({})
    det = solver.detectStars(img)

    assert numpy.hypot(det[:, 0] - 700, det[:, 1] - 500).min() < 1.5
    blob_detections = numpy.hypot(det[:, 0] - 150, det[:, 1] - 150) < 20
    assert numpy.sum(blob_detections) == 1
