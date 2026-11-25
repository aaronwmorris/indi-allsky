import pytest

from indi_allsky.focus.gearing import MSG_GEAR_LIMIT_UNSET
from indi_allsky.focus.gearing import MSG_GEAR_UNSET
from indi_allsky.focus.gearing import MSG_LIMIT_UNSET
from indi_allsky.focus.gearing import config_unset_reason
from indi_allsky.focus.gearing import unset_reason


@pytest.mark.parametrize('motor, lens, limit, want', [
    (12, 82, 30, None),
    (0, 82, 30, MSG_GEAR_UNSET),
    (12, 0, 30, MSG_GEAR_UNSET),
    (12, 82, 0, MSG_LIMIT_UNSET),
    (0, 0, 0, MSG_GEAR_LIMIT_UNSET),
    (None, None, None, MSG_GEAR_LIMIT_UNSET),
])
def test_unset_reason_names_what_config_is_missing(motor, lens, limit, want):
    assert unset_reason(motor, lens, limit) == want


def test_no_focuser_means_nothing_to_set():
    assert config_unset_reason({'CLASSNAME': '', 'GEAR_MOTOR_TEETH': 0}) is None


def test_a_focuser_reads_its_config_block():
    block = {'CLASSNAME': 'focuser_28byj_64', 'GEAR_MOTOR_TEETH': 12, 'GEAR_LENS_TEETH': 82, 'TRAVEL_LIMIT_LENS_DEGREES': 0}
    assert config_unset_reason(block) == MSG_LIMIT_UNSET
    assert config_unset_reason(dict(block, TRAVEL_LIMIT_LENS_DEGREES=30)) is None
