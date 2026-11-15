"""Provision the single NetworkManager AP profile owned or adopted by Wi-Fi recovery."""
import configparser
from io import StringIO
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import uuid


SYSTEM_CONNECTIONS = Path('/etc/NetworkManager/system-connections')
GATEWAY = '10.42.0.1'


def nm(*args):
    return subprocess.run(['nmcli', '--escape', 'no', *args], check=True, capture_output=True,
                          text=True).stdout.rstrip('\n')


def field(profile, name):
    return nm('-g', name, 'connection', 'show', 'uuid', profile)


def store(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        try:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(stream.name, path)
        finally:
            Path(stream.name).unlink(missing_ok=True)


def new_keyfile(interface, profile):
    suffix = profile[-4:].upper()
    conf = configparser.ConfigParser(interpolation=None)
    conf.read_dict({
        'connection': {'id': f'indi-allsky fallback {interface}', 'uuid': profile,
                       'type': 'wifi', 'interface-name': interface, 'autoconnect': 'false'},
        'wifi': {'mode': 'ap', 'ssid': 'IndiAllsky-' + suffix, 'band': 'bg', 'powersave': '2'},
        'wifi-security': {'key-mgmt': 'wpa-psk', 'proto': 'rsn;', 'pairwise': 'ccmp;',
                          'group': 'ccmp;', 'psk': secrets.token_hex(12)},
        'ipv4': {'method': 'shared', 'address1': GATEWAY + '/24'},
        'ipv6': {'method': 'link-local'},
    })
    contents = StringIO()
    conf.write(contents, space_around_delimiters=False)
    return contents.getvalue()


def owned_file(interface):
    return SYSTEM_CONNECTIONS / f'indi-allsky-fallback-{interface}.nmconnection'


def matching_keyfile(path, profile):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('The dedicated AP keyfile is not a root-owned mode 0600 regular file.')
    conf = configparser.ConfigParser(interpolation=None)
    conf.read(path)
    if conf.get('connection', 'uuid', fallback='') != profile:
        raise ValueError('A different profile already uses the dedicated AP keyfile path.')


def check_profile(interface, profile):
    if (field(profile, 'connection.type') != '802-11-wireless'
            or field(profile, 'connection.interface-name') != interface
            or field(profile, '802-11-wireless.mode') != 'ap'
            or field(profile, 'ipv4.method') != 'shared'
            or GATEWAY + '/24' not in field(profile, 'ipv4.addresses').split(',')
            or field(profile, '802-11-wireless-security.key-mgmt') != 'wpa-psk'
            or any(field(profile, '802-11-wireless-security.' + prop) != value
                   for prop, value in (('proto', 'rsn'), ('pairwise', 'ccmp'), ('group', 'ccmp')))):
        raise ValueError('AP must be bound to this interface, use shared 10.42.0.1/24 and WPA2-PSK/CCMP.')


def available_aps(interface):
    profiles = []
    for profile in nm('-g', 'UUID', 'connection', 'show').splitlines():
        if (field(profile, 'connection.type') == '802-11-wireless'
                and field(profile, '802-11-wireless.mode') == 'ap'
                and field(profile, 'connection.interface-name') in ('', interface)):
            profiles.append(profile)
    return profiles


def recognized_project_ap(profile):
    name = field(profile, 'connection.id').casefold()
    return name in ('indi-allsky hotspot', 'indiallsky') or (
        name == 'hotspot' and field(profile, '802-11-wireless.ssid').casefold() == 'indiallsky')


def install_ap(interface, directory, requested, check_only=False):
    record = directory / 'ap.json'
    marker = directory / 'ap.uuid'
    if record.exists():
        data = json.loads(record.read_text())
        if requested and data['uuid'] != requested:
            raise ValueError('This interface already has a managed AP. Remove it before selecting a different one.')
        if data['adopted']:
            check_profile(interface, data['uuid'])
    else:
        if marker.exists():
            raise ValueError('Missing AP ownership record; refusing to replace the selected profile.')
        existing = [requested] if requested else available_aps(interface)
        if not requested and existing:
            if len(existing) != 1 or not recognized_project_ap(existing[0]):
                raise ValueError('An AP is already configured. Pass its UUID explicitly to adopt it; other profiles are preserved.')
        if existing:
            profile = str(uuid.UUID(existing[0]))
            check_profile(interface, profile)
            auto = field(profile, 'connection.autoconnect')
            if auto not in ('yes', 'no'):
                raise ValueError('Cannot determine original AP autoconnect setting.')
            data = {'uuid': profile, 'adopted': True, 'autoconnect': auto}
        else:
            if os.path.lexists(owned_file(interface)):
                raise ValueError('A keyfile already uses the dedicated fallback path; refusing to overwrite it.')
            data = {'uuid': str(uuid.uuid4()), 'adopted': False}
        if not check_only:
            store(record, json.dumps(data) + '\n')

    if check_only:
        return
    profile = data['uuid']
    if not data['adopted']:
        path = owned_file(interface)
        if os.path.lexists(path):
            matching_keyfile(path, profile)
        else:
            store(path, new_keyfile(interface, profile))
        nm('connection', 'load', str(path))
    check_profile(interface, profile)
    name = field(profile, '802-11-wireless.ssid')
    store(marker, profile + '\n')
    # This is the last mutating install operation. If it fails, an adopted AP
    # still has its original policy; its restoration record is already durable.
    if field(profile, 'connection.autoconnect') != 'no':
        nm('connection', 'modify', 'uuid', profile, 'connection.autoconnect', 'no')
    print('Fallback Wi-Fi:', name)
    print('Camera:', 'https://' + GATEWAY + '/indi-allsky/')


def remove_ap(interface, directory):
    record = directory / 'ap.json'
    if not record.exists():
        return
    data = json.loads(record.read_text())
    profile = data['uuid']
    present = profile in nm('-g', 'UUID', 'connection', 'show').splitlines()
    if data['adopted']:
        if present and field(profile, 'connection.autoconnect') == 'no' and data['autoconnect'] == 'yes':
            nm('connection', 'modify', 'uuid', profile, 'connection.autoconnect', 'yes')
    else:
        path = owned_file(interface)
        if os.path.lexists(path):
            matching_keyfile(path, profile)
            if present:
                nm('connection', 'delete', 'uuid', profile)
            path.unlink(missing_ok=True)
        elif present:
            raise ValueError('AP profile exists but its dedicated keyfile is missing. Resolve ownership before removal.')
    (directory / 'ap.uuid').unlink(missing_ok=True)
    record.unlink()


def credentials(interface, directory):
    profile = (directory / 'ap.uuid').read_text().strip()
    check_profile(interface, profile)
    print('SSID:', field(profile, '802-11-wireless.ssid'))
    print('Password:', nm('--show-secrets', '-g', '802-11-wireless-security.psk',
                          'connection', 'show', 'uuid', profile))
    print('Camera:', 'https://' + GATEWAY + '/indi-allsky/')


if __name__ == '__main__':
    action, interface, state, *rest = sys.argv[1:]
    try:
        if os.geteuid() != 0:
            raise ValueError('Use the root setup script to manage access point profiles.')
        if action in ('install', 'check'):
            install_ap(interface, Path(state), rest[0] if rest else None, check_only=action == 'check')
        elif action == 'remove':
            remove_ap(interface, Path(state))
        elif action == 'credentials':
            credentials(interface, Path(state))
        else:
            raise ValueError('Unknown AP operation.')
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        # nmcli invocations never contain credentials. Its stderr need not be logged.
        sys.exit(str(exc))
