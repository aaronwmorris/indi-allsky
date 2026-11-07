#!/usr/bin/env python3
"""Retry an existing Wi-Fi station profile after NetworkManager has stayed idle."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import time


NM = 'org.freedesktop.NetworkManager'
NM_PATH = '/org/freedesktop/NetworkManager'
DEVICE = NM + '.Device'
WIRELESS = DEVICE + '.Wireless'
PROPERTIES = 'org.freedesktop.DBus.Properties'
DISCONNECTED = 30
USER_REQUESTED = 39

GRACE_SECONDS = 120
COOLDOWN_SECONDS = 300
MAX_ATTEMPTS_PER_HOUR = 3
AP_MAX_AGE_SECONDS = 90
STALLED_SECONDS = 600
STALLED_MESSAGES = {
    'ip-config': 'IP configuration is still pending.',
    'connecting': 'NetworkManager connection activation is still pending.',
    'no-carrier': 'NetworkManager reports activated without an access point or kernel carrier.',
}


class NetworkManager:
    def __init__(self, interface):
        import dbus
        self.dbus = dbus
        self.bus = dbus.SystemBus()
        # Address the running owner. Do not start NetworkManager when it is stopped.
        self.owner = self.bus.get_name_owner(NM)
        self.manager = dbus.Interface(self.object(NM_PATH), NM)
        self.device = self.manager.GetDeviceByIpIface(interface)
        self.interface = interface

    def object(self, path):
        return self.bus.get_object(self.owner, path)

    def properties(self, path, interface):
        props = self.dbus.Interface(self.object(path), PROPERTIES)
        return props.GetAll(interface)

    def settings(self, path):
        connection = self.dbus.Interface(self.object(path), NM + '.Settings.Connection')
        return connection.GetSettings()

    def carrier_missing(self):
        try:
            return (Path('/sys/class/net') / self.interface / 'carrier').read_text().strip() == '0'
        except OSError:
            return False

    def condition(self):
        system = self.properties(NM_PATH, NM)
        if not all(system[key] for key in ('NetworkingEnabled', 'WirelessEnabled', 'WirelessHardwareEnabled')):
            return None
        device = self.properties(self.device, DEVICE)
        if (device['DeviceType'] != 2 or not device['Managed'] or not device['Autoconnect']
                or device['StateReason'][1] == USER_REQUESTED):
            return None
        wireless = self.properties(self.device, WIRELESS)
        if wireless['Mode'] not in (0, 2):  # unknown or infrastructure
            return None
        if device['State'] == DISCONNECTED and device['ActiveConnection'] == '/':
            return 'disconnected'
        if device['State'] == 70:
            return 'ip-config'
        if device['State'] in (40, 50, 60, 80, 90):
            return 'connecting'
        if device['State'] == 100 and wireless['ActiveAccessPoint'] == '/' and self.carrier_missing():
            return 'no-carrier'
        return None

    def profiles(self, now):
        wireless = self.properties(self.device, WIRELESS)
        visible = set()
        for path in wireless['AccessPoints']:
            ap = self.properties(path, NM + '.AccessPoint')
            if (ap['Mode'] == 2 and ap['Ssid'] and ap['LastSeen'] >= 0
                    and 0 <= now - ap['LastSeen'] <= AP_MAX_AGE_SECONDS):
                visible.add(bytes(ap['Ssid']))
        if not visible:
            return []

        candidates = []
        for path in self.properties(self.device, DEVICE)['AvailableConnections']:
            settings = self.settings(path)
            con = settings['connection']
            wifi = settings.get('802-11-wireless', {})
            if con['type'] != '802-11-wireless' or not con.get('autoconnect', True):
                continue
            if wifi.get('mode', 'infrastructure') != 'infrastructure' or bytes(wifi.get('ssid', b'')) not in visible:
                continue
            candidates.append((int(con.get('autoconnect-priority', 0)), int(con.get('timestamp', 0)), path))
        return [path for _, _, path in sorted(candidates, reverse=True)]

    def activate(self, profile):
        # '/' lets NetworkManager select the AP. Never create a profile or pin a BSSID.
        self.manager.ActivateConnection(profile, self.device, '/')

    def scan_overdue(self, now):
        last_scan = self.properties(self.device, WIRELESS)['LastScan']
        return last_scan < 0 or now - last_scan / 1000 >= COOLDOWN_SECONDS

    def request_scan(self):
        wifi = self.dbus.Interface(self.object(self.device), WIRELESS)
        wifi.RequestScan(self.dbus.Dictionary(signature='sv'))


def scan_if_stale(network, history, now, condition, save):
    last_request = history.get('scan', -COOLDOWN_SECONDS)
    if now - last_request < COOLDOWN_SECONDS or not network.scan_overdue(now):
        return
    if network.condition() == condition:
        history['scan'] = now
        save(history)
        network.request_scan()


def check(network, history, now, save):
    """Record attempt times before activation, including attempts rejected by NM."""
    attempts = [stamp for stamp in history.get('attempts', []) if 0 <= now - stamp < 3600]
    history['attempts'] = attempts
    condition = network.condition()
    if not condition:
        history.pop('condition', None)
        history.pop('since', None)
        history.pop('reported', None)
        save(history)
        return
    if condition != history.get('condition') or now < history.get('since', now):
        history['condition'] = condition
        history['since'] = now
        history.pop('reported', None)
    save(history)
    elapsed = now - history['since']
    if condition != 'disconnected':
        if elapsed >= STALLED_SECONDS:
            if not history.get('reported'):
                print(STALLED_MESSAGES[condition], flush=True)
                history['reported'] = True
                save(history)
            if condition == 'no-carrier':
                scan_if_stale(network, history, now, condition, save)
        return
    if elapsed < GRACE_SECONDS or len(attempts) >= MAX_ATTEMPTS_PER_HOUR:
        return
    if attempts and now - attempts[-1] < COOLDOWN_SECONDS:
        return

    profiles = network.profiles(now)
    if network.condition() != 'disconnected':
        return
    if not profiles:
        scan_if_stale(network, history, now, condition, save)
        return
    history['attempts'].append(now)
    save(history)
    network.activate(profiles[0])
    print('Requested activation of an available saved station profile.', flush=True)


def main():
    import dbus
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('interface')
    args = parser.parse_args()
    directory = Path(os.environ['RUNTIME_DIRECTORY'])
    state = directory / 'state.json'

    def save(history):
        if not history.get('attempts') and 'since' not in history and not state.exists():
            return
        data = json.dumps(history)
        if state.exists() and state.read_text() == data:
            return
        tmp = directory / 'state.tmp'
        tmp.write_text(data)
        tmp.replace(state)

    with (directory / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        history = json.loads(state.read_text()) if state.exists() else {}
        try:
            network = NetworkManager(args.interface)
            check(network, history, int(time.clock_gettime(time.CLOCK_BOOTTIME)), save)
        except dbus.DBusException as error:
            # NM may stop, or a scan result may disappear during enumeration.
            # Never expose connection names, access points or credentials in our log.
            print('NetworkManager request unavailable (' + str(error.get_dbus_name()) + ').', flush=True)


if __name__ == '__main__':
    main()
