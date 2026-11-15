"""Exercise AP ownership and rollback with an in-memory NetworkManager."""
import configparser
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'wifi_recovery_ap', Path(__file__).resolve().parents[1] / 'misc' / 'wifi_recovery_ap.py')
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)
EXISTING = '12345678-9e9b-4d96-8286-a0931ae73ad2'
SECOND = 'eb7ca130-f517-4894-9bc3-0048960ecffd'


class FakeManager:
    def __init__(self):
        self.profiles = {}
        self.operations = []

    def profile(self, identifier, name='indi-allsky Hotspot', **extra):
        self.profiles[identifier] = {
            'connection.id': name, 'connection.type': '802-11-wireless',
            'connection.interface-name': 'wlan0', '802-11-wireless.mode': 'ap',
            'connection.autoconnect': 'yes', 'ipv4.method': 'shared', 'ipv4.addresses': '10.42.0.1/24',
            '802-11-wireless.ssid': 'original SSID',
            '802-11-wireless-security.key-mgmt': 'wpa-psk', '802-11-wireless-security.proto': 'rsn',
            '802-11-wireless-security.pairwise': 'ccmp', '802-11-wireless-security.group': 'ccmp', **extra,
        }

    def __call__(self, *args):
        if args == ('-g', 'UUID', 'connection', 'show'):
            return '\n'.join(self.profiles)
        if args[0] == '-g':
            return self.profiles[args[5]][args[1]]
        self.operations.append(args)
        if args[:2] == ('connection', 'modify'):
            self.profiles[args[3]][args[4]] = args[5]
        elif args[:2] == ('connection', 'load'):
            config = configparser.ConfigParser()
            config.read(args[2])
            self.profile(config['connection']['uuid'], name=config['connection']['id'], **{
                'connection.autoconnect': 'no', '802-11-wireless.ssid': config['wifi']['ssid']})
        else:
            raise AssertionError(f'Unexpected request {args!r}')


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        self.nm = FakeManager()
        for change in (patch.object(ap, 'nm', self.nm), patch.object(ap, 'SYSTEM_CONNECTIONS', self.root)):
            change.start()
            self.addCleanup(change.stop)

    def test_adoption_preserves_every_property_except_autoconnect_and_restores_it(self):
        self.nm.profile(EXISTING)
        original = self.nm.profiles[EXISTING].copy()
        ap.install_ap('wlan0', self.state, EXISTING)
        ap.install_ap('wlan0', self.state, None)
        self.assertEqual(self.nm.profiles[EXISTING], dict(original, **{'connection.autoconnect': 'no'}))
        self.assertEqual((self.state/'ap.uuid').read_text(), EXISTING + '\n')
        self.assertEqual((self.state/'ap.uuid').stat().st_mode & 0o777, 0o600)
        ap.remove_ap('wlan0', self.state)
        self.assertEqual(self.nm.profiles[EXISTING], original)
        self.assertEqual([cmd[:2] for cmd in self.nm.operations], [('connection','modify')]*2)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_explicit_profile_required_when_several_aps_exist(self):
        self.nm.profile(EXISTING)
        self.nm.profile(SECOND, name='another hotspot')
        with self.assertRaisesRegex(ValueError, 'UUID explicitly'):
            ap.install_ap('wlan0', self.state, None)
        self.assertFalse(self.nm.operations)
        ap.install_ap('wlan0', self.state, EXISTING)
        self.assertEqual(self.nm.profiles[SECOND]['connection.autoconnect'], 'yes')

    def test_does_not_adopt_unknown_profile_by_name_or_modify_open_ap(self):
        self.nm.profile(EXISTING, name='Other network')
        with self.assertRaisesRegex(ValueError, 'UUID explicitly'):
            ap.install_ap('wlan0', self.state, None)
        self.nm.profiles[EXISTING]['802-11-wireless-security.key-mgmt'] = ''
        with self.assertRaisesRegex(ValueError, 'WPA2'):
            ap.install_ap('wlan0', self.state, EXISTING)
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertFalse(self.nm.operations)

    def test_preflight_and_unrelated_named_hotspot_do_not_change_any_setting(self):
        self.nm.profile(EXISTING)
        ap.install_ap('wlan0', self.state, EXISTING, check_only=True)
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertFalse(self.nm.operations)
        self.nm.profiles[EXISTING]['connection.id'] = 'HotSpot'
        with self.assertRaisesRegex(ValueError, 'UUID explicitly'):
            ap.install_ap('wlan0', self.state, None)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_interrupted_adoption_is_idempotent_and_has_original_autoconnect_record(self):
        import json
        self.nm.profile(EXISTING)

        def fail_once(*args):
            if args[:2] == ('connection', 'modify'):
                raise OSError('NetworkManager unavailable')
            return self.nm(*args)

        with patch.object(ap, 'nm', fail_once), self.assertRaises(OSError):
            ap.install_ap('wlan0', self.state, EXISTING)
        self.assertEqual(self.nm.profiles[EXISTING]['connection.autoconnect'], 'yes')
        self.assertEqual(json.loads((self.state/'ap.json').read_text())['autoconnect'], 'yes')
        ap.install_ap('wlan0', self.state, EXISTING)
        self.assertEqual(self.nm.profiles[EXISTING]['connection.autoconnect'], 'no')

    def test_new_profile_is_private_shared_and_never_activated_during_install(self):
        ap.install_ap('wlan0', self.state, None)
        profile = (self.state/'ap.uuid').read_text().strip()
        self.assertIn(profile, self.nm.profiles)
        path = ap.owned_file('wlan0')
        cfg = configparser.ConfigParser()
        cfg.read(path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(cfg['connection']['autoconnect'], 'false')
        self.assertEqual(cfg['ipv4']['address1'], '10.42.0.1/24')
        self.assertEqual(cfg['wifi-security']['proto'], 'rsn;')
        self.assertRegex(cfg['wifi-security']['psk'], '^[0-9a-f]{24}$')
        self.assertNotIn(cfg['wifi-security']['psk'], (self.state/'ap.json').read_text())
        self.assertEqual(self.nm.operations, [('connection','load',str(path))])

    def test_existing_unmanaged_keyfile_never_overwritten(self):
        ap.owned_file('wlan0').write_text('do not touch')
        with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
            ap.install_ap('wlan0', self.state, None)
        self.assertEqual(ap.owned_file('wlan0').read_text(), 'do not touch')
        self.assertEqual(list(self.state.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
