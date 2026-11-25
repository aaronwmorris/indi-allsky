import numpy as np

import indi_allsky.flask  # noqa: F401
from indi_allsky.processing import ImageProcessor


class TestWhiteBalanceAutoBgr:
    def test_balances_uint8_and_uint16_images(self):
        for dtype, vals in (
            (np.uint8, [[[50, 100, 150], [100, 150, 200]]]),
            (np.uint16, [[[5000, 10000, 15000], [10000, 15000, 20000]]]),
        ):
            processor = ImageProcessor.__new__(ImageProcessor)
            processor.image = np.array(vals, dtype=dtype)

            processor._white_balance_auto_bgr()

            assert processor.image.dtype == dtype
            assert processor.image.shape == (1, 2, 3)

            b_mean = float(processor.image[:, :, 0].mean())
            g_mean = float(processor.image[:, :, 1].mean())
            r_mean = float(processor.image[:, :, 2].mean())
            assert abs(b_mean - g_mean) <= 1.0
            assert abs(r_mean - g_mean) <= 1.0

    def test_saturates_without_overflow_on_uint16(self):
        processor = ImageProcessor.__new__(ImageProcessor)
        processor.image = np.array([[[10000, 30000, 60000]]], dtype=np.uint16)

        processor._white_balance_auto_bgr()

        assert processor.image.dtype == np.uint16
        assert int(processor.image[0, 0, 0]) == 33333
        assert int(processor.image[0, 0, 1]) == 33333
        assert int(processor.image[0, 0, 2]) <= 65535
