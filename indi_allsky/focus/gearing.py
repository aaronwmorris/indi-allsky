"""The focuser's gearing: what capture needs to turn lens degrees into motor steps.

The lens ring sets the true travel limits, so the limit is in lens degrees. The motor turns the lens through two
external gears; without their tooth counts a lens degree has no motor-step size. The web page and capture both ask
`unset_reason` so the page can say why the lens buttons are off before a session starts.
"""

from typing import Optional

MSG_GEAR_UNSET = "Set the focuser's gear teeth in Config."
MSG_LIMIT_UNSET = "Set the focuser's lens travel limit in Config."
MSG_GEAR_LIMIT_UNSET = "Set the focuser's gear teeth and lens travel limit in Config."


def unset_reason(motor_teeth, lens_teeth, limit_lens_degrees) -> Optional[str]:
    """Why a configured focus motor cannot be used yet, or None."""
    gear = int(motor_teeth or 0) < 1 or int(lens_teeth or 0) < 1
    limit = float(limit_lens_degrees or 0) <= 0
    if gear and limit:
        return MSG_GEAR_LIMIT_UNSET
    if gear:
        return MSG_GEAR_UNSET
    if limit:
        return MSG_LIMIT_UNSET
    return None


def config_unset_reason(focuser_config) -> Optional[str]:
    """`unset_reason` for a FOCUSER config block; None when no focuser is configured."""
    if not focuser_config.get('CLASSNAME'):
        return None
    return unset_reason(focuser_config.get('GEAR_MOTOR_TEETH'), focuser_config.get('GEAR_LENS_TEETH'),
                        focuser_config.get('TRAVEL_LIMIT_LENS_DEGREES'))
