"""Derive a compact battery reading from the selected camera's own sensor data."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path


_FRESH_SECONDS = 120


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def battery_reading(probes, metadata, image, now, camera, config):
    # Select channels by the driver's probe name, even when users rename or move the HAT.
    channels = [(slot, device) for slot, (device, probe) in sorted(probes.items()) if probe == 'battery percent (%)']
    if not channels:
        has_battery = any(probe in ('remaining capacity (mah)', 'battery voltage (mv)') for _, probe in probes.values())
        return {} if has_battery else None
    if not image:
        return {}
    if image['time_source'] == 'file':
        # latest.<ext> has no associated database row. Its companion status snapshot
        # is station-local; verify the camera identity after a device change.
        if not camera.local:
            return {}
        path = Path(config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')) / 'indi_allsky_status.json'
        try:
            with path.open(encoding='utf-8') as stream:
                metadata = json.load(stream)
        except (OSError, ValueError):
            return {}
        if not isinstance(metadata, dict) or not camera.uuid or metadata.get('camera_uuid') != camera.uuid:
            return {}
        stamp = _number(metadata.get('time'))
    else:
        stamp = datetime.fromisoformat(image['captured_at']).timestamp()
    if not isinstance(metadata, dict) or stamp is None:
        return {}

    mask = metadata.get('sensor_valid_mask')
    if mask is not None and (type(mask) is not int or mask < 0):
        return {}

    for slot, device in channels:
        if mask is not None and not mask & (1 << (slot - 10)):
            continue
        value = _number(metadata.get(f'sensor_user_{slot}'))
        if value is None or not 0 <= value <= 100:
            continue
        if mask is None and value == 0:
            # Older stations initialize every channel to zero before the first I2C read.
            voltage_slot = next((i for i, probe in probes.items() if probe == (device, 'battery voltage (mv)')), None)
            if voltage_slot is not None and (_number(metadata.get(f'sensor_user_{voltage_slot}')) or 0) <= 0:
                continue
        observed = stamp
        last_good = metadata.get('sensor_last_good')
        if camera.local and device in ('a', 'b', 'c', 'd', 'e', 'f') and isinstance(last_good, list):
            index = ord(device) - ord('a')
            observed = _number(last_good[index]) if index < len(last_good) else None
        if observed is None or not 0 <= now.timestamp() - observed < _FRESH_SECONDS:
            continue
        return {'value': value, 'sampled_at': datetime.fromtimestamp(observed, timezone.utc).isoformat(),
                'expires_at': datetime.fromtimestamp(observed + _FRESH_SECONDS, timezone.utc).isoformat()}
    return {}
