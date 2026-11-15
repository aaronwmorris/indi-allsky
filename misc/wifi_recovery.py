#!/usr/bin/env python3
"""Retry an existing Wi-Fi station profile after NetworkManager has stayed idle."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import UUID


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
AP_WAIT_SECONDS = 300       # Maximum time to wait for a usable station
AP_PROBE_INTERVAL = 600     # Keep the AP available between station searches
AP_SCAN_SECONDS = 16        # Stop the search sooner when a completed scan has no candidate
CHECKPOINT_SECONDS = 30     # NM will restore the AP even if the service dies during scanning
AP_PROBE_WINDOW = 180       # Only an actual station attempt may keep the AP down for DHCP
DHCP_CHECKPOINT_SECONDS = AP_PROBE_WINDOW + 90  # let the timer confirm a late successful association
STALLED_SECONDS = 600
STALLED_MESSAGES = {
    'ip-config': 'IP configuration is still pending.',
    'connecting': 'NetworkManager connection activation is still pending.',
    'reconnecting': 'NetworkManager is still changing connections.',
    'no-carrier': 'NetworkManager reports activated without an access point or kernel carrier.',
}


class NetworkManager:
    def __init__(self, interface, ap_uuid=None):
        import dbus
        self.dbus = dbus
        self.bus = dbus.SystemBus()
        # Address the running owner. Do not start NetworkManager when it is stopped.
        self.owner = self.bus.get_name_owner(NM)
        self.manager = dbus.Interface(self.object(NM_PATH), NM)
        self.device = self.manager.GetDeviceByIpIface(interface)
        self.interface = interface
        self.ap_uuid = ap_uuid

    def object(self, path):
        return self.bus.get_object(self.owner, path)

    def properties(self, path, interface):
        props = self.dbus.Interface(self.object(path), PROPERTIES)
        return props.GetAll(interface, timeout=3)

    def settings(self, path):
        connection = self.dbus.Interface(self.object(path), NM + '.Settings.Connection')
        return connection.GetSettings(timeout=3)

    def carrier_missing(self):
        try:
            return (Path('/sys/class/net') / self.interface / 'carrier').read_text().strip() == '0'
        except OSError:
            return False

    def condition(self, probing=False):
        system = self.properties(NM_PATH, NM)
        if not all(system[key] for key in ('NetworkingEnabled', 'WirelessEnabled', 'WirelessHardwareEnabled')):
            return None
        device = self.properties(self.device, DEVICE)
        if device['DeviceType'] != 2 or not device['Managed'] or not device['Autoconnect']:
            return None
        if device['StateReason'][1] == USER_REQUESTED and not (probing and device['State'] in (DISCONNECTED, 110, 120)):
            return None
        wireless = self.properties(self.device, WIRELESS)
        if getattr(self, 'ap_uuid', None) and device['ActiveConnection'] != '/':
            active = self.properties(device['ActiveConnection'], NM + '.Connection.Active')
            if active['Uuid'] == self.ap_uuid:
                if wireless['Mode'] == 3 and device['State'] == 100:
                    return 'fallback-ap'
                if device['State'] in (40, 50, 60, 70, 80, 90):
                    return 'starting-ap'
                if probing and device['State'] in (110, 120):
                    return 'probe-transition'
                return None
            if self.settings(active['Connection']).get('802-11-wireless', {}).get('mode') == 'ap':
                return None  # another hotspot, including one still activating
        if getattr(self, 'ap_uuid', None) and device['State'] in (110, 120):
            return 'probe-transition' if probing else 'reconnecting'
        if probing and device['State'] == DISCONNECTED and device['ActiveConnection'] == '/':
            return 'disconnected'
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

    def profiles(self, now, seen_since=0, deadline=None):
        wireless = self.properties(self.device, WIRELESS)
        visible = set()
        for path in wireless['AccessPoints']:
            if deadline is not None and boottime() >= deadline:
                return []
            ap = self.properties(path, NM + '.AccessPoint')
            if (ap['Mode'] == 2 and ap['Ssid'] and ap['LastSeen'] >= seen_since
                    and 0 <= now - ap['LastSeen'] <= AP_MAX_AGE_SECONDS):
                visible.add(bytes(ap['Ssid']))
        if not visible:
            return []

        candidates = []
        for path in self.properties(self.device, DEVICE)['AvailableConnections']:
            if deadline is not None and boottime() >= deadline:
                return []
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
        self.manager.ActivateConnection(profile, self.device, '/', timeout=4)

    def fallback_profile(self):
        settings = self.dbus.Interface(self.object(NM_PATH + '/Settings'), NM + '.Settings')
        path = settings.GetConnectionByUuid(self.ap_uuid)
        config = self.settings(path)
        con = config['connection']
        security = config.get('802-11-wireless-security', {})
        protocols = security.get('proto', [])
        if (con.get('uuid') != self.ap_uuid or con.get('type') != '802-11-wireless'
                or con.get('interface-name') not in (None, '', self.interface)
                or config.get('802-11-wireless', {}).get('mode') != 'ap'
                or security.get('key-mgmt') != 'wpa-psk' or (protocols and 'rsn' not in protocols)
                or config.get('ipv4', {}).get('method') != 'shared'):
            raise ValueError('The installed access-point profile no longer matches its interface, security or IP settings.')
        return path

    def ap_idle(self):
        # NetworkManager has no list of stations associated to our own AP.
        # Only a successful empty kernel station dump means it is safe to probe.
        try:
            result = subprocess.run(['/usr/sbin/iw', 'dev', self.interface, 'station', 'dump'],
                                    capture_output=True, timeout=4, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and not result.stdout.strip()

    def checkpoint(self):
        return str(self.manager.CheckpointCreate([self.device], CHECKPOINT_SECONDS, 0, timeout=4))

    def allow_dhcp(self, probe):
        self.manager.CheckpointAdjustRollbackTimeout(probe['checkpoint'], DHCP_CHECKPOINT_SECONDS, timeout=4)

    def finish_checkpoint(self, probe, restore):
        if probe['owner'] != self.owner or probe['checkpoint'] not in self.properties(NM_PATH, NM)['Checkpoints']:
            return False
        if restore:
            result = self.manager.CheckpointRollback(probe['checkpoint'], timeout=6)
            return result.get(self.device) == 0
        self.manager.CheckpointDestroy(probe['checkpoint'], timeout=4)
        return True

    def leave_own_ap(self):
        active = self.properties(self.device, DEVICE)['ActiveConnection']
        if (active != '/' and self.properties(active, NM + '.Connection.Active')['Uuid'] == self.ap_uuid
                and self.ap_idle()):
            # Device.Disconnect() would also disable automatic reconnection.
            self.manager.DeactivateConnection(active, timeout=4)
            return True
        return False

    def scan_overdue(self, now):
        last_scan = self.properties(self.device, WIRELESS)['LastScan']
        return last_scan < 0 or now - last_scan / 1000 >= COOLDOWN_SECONDS

    def station_pending(self):
        active = self.properties(self.device, DEVICE)['ActiveConnection']
        if active == '/':
            return False
        config = self.settings(self.properties(active, NM + '.Connection.Active')['Connection'])
        return (config['connection'].get('type') == '802-11-wireless'
                and config.get('802-11-wireless', {}).get('mode', 'infrastructure') == 'infrastructure')

    def scan_finished_since(self, start):
        return self.properties(self.device, WIRELESS)['LastScan'] >= int(start * 1000)

    def request_probe_scan(self):
        try:
            self.request_scan()
        except self.dbus.DBusException as exc:
            # NM may already be performing an automatic scan. Watch LastScan
            # for its result and keep the same short rollback deadline.
            if exc.get_dbus_name() != NM + '.Device.NotAllowed':
                raise

    def request_scan(self):
        wifi = self.dbus.Interface(self.object(self.device), WIRELESS)
        wifi.RequestScan(self.dbus.Dictionary(signature='sv'), timeout=4)


def scan_if_stale(network, history, now, condition, save):
    last_request = history.get('scan', -COOLDOWN_SECONDS)
    if now - last_request < COOLDOWN_SECONDS or not network.scan_overdue(now):
        return
    if network.condition() == condition:
        history['scan'] = now
        save(history)
        network.request_scan()


def check_station(network, history, now, condition, save):
    attempts = history['attempts']
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


def offer_fallback(network, history, now, condition, save):
    # Re-check after profile lookup: native autoconnect may just have succeeded.
    if now - history.get('ap_attempt', -GRACE_SECONDS) < GRACE_SECONDS:
        return
    profile = network.fallback_profile()
    if network.condition() == condition:
        history['ap_attempt'] = now
        save(history)
        network.activate(profile)
        print('Requested activation of the camera access point.', flush=True)


def boottime():
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def finish_probe(network, history, save, *, restore):
    probe = history['probe']
    protected = (None, 'starting-ap', 'fallback-ap')
    if restore and network.condition(probing=True) not in protected:
        try:
            profile = network.fallback_profile()
        except ValueError:
            network.finish_checkpoint(probe, restore=False)
            del history['probe']
            save(history)
            raise
        if network.condition(probing=True) not in protected:
            if not network.finish_checkpoint(probe, restore=True) and network.condition(probing=True) not in protected:
                network.activate(profile)
        else:
            network.finish_checkpoint(probe, restore=False)
    else:
        network.finish_checkpoint(probe, restore=False)
    del history['probe']
    save(history)


def allow_station_time(network, probe, history, save):
    # The short NM safety timeout is extended only after a station activation
    # has been accepted or we have observed NM starting one of its own.
    network.allow_dhcp(probe)
    probe['until'] = int(boottime()) + AP_PROBE_WINDOW
    save(history)


def scan_for_station(network, history, save):
    probe = history['probe']
    start = boottime()
    deadline = start + AP_SCAN_SECONDS
    requested = False
    while boottime() < deadline:
        condition = network.condition(probing=True)
        if condition is None or (condition == 'fallback-ap' and not network.ap_idle()):
            finish_probe(network, history, save, restore=False)
            return
        if condition in ('connecting', 'ip-config') and network.station_pending():
            allow_station_time(network, probe, history, save)
            return
        if condition == 'disconnected':
            if not requested:
                requested = True
                network.request_probe_scan()
            if network.scan_finished_since(start):
                # A previous scan may still have stale entries in NM's cache.
                candidates = network.profiles(boottime(), seen_since=int(start), deadline=deadline)
                if network.condition(probing=True) == 'disconnected':
                    if candidates and len(history['attempts']) < MAX_ATTEMPTS_PER_HOUR:
                        history['attempts'].append(int(boottime()))
                        save(history)
                        network.activate(candidates[0])
                        allow_station_time(network, probe, history, save)
                        return
                    break
        time.sleep(min(2, max(0, deadline - boottime())))
    finish_probe(network, history, save, restore=True)


def check_probe(network, history, now, condition, save):
    if condition in (None, 'fallback-ap', 'starting-ap'):
        finish_probe(network, history, save, restore=False)
    elif condition == 'disconnected' or now >= history['probe']['until']:
        finish_probe(network, history, save, restore=True)


def check(network, history, now, save):
    """Record attempts before modifying the interface. All times use the boot clock."""
    history['attempts'] = [stamp for stamp in history.get('attempts', []) if 0 <= now - stamp < 3600]
    if not getattr(network, 'ap_uuid', None):
        check_station(network, history, now, network.condition(), save)
        return

    probe = history.get('probe')
    condition = network.condition(probing=bool(probe))
    if probe:
        check_probe(network, history, now, condition, save)
        return
    if condition == 'fallback-ap':
        history.pop('outage_since', None)
        next_probe = history.setdefault('next_probe', now + AP_PROBE_INTERVAL)
        if now >= next_probe and network.ap_idle():
            network.fallback_profile()
            if network.condition() == 'fallback-ap' and network.ap_idle():
                # The AP may be the operator's only route to this device.
                # Take a time-limited NM checkpoint before dropping it.
                history['next_probe'] = now + AP_PROBE_INTERVAL
                save(history)
                history['probe'] = dict(checkpoint=network.checkpoint(), owner=str(network.owner),
                                        until=now + CHECKPOINT_SECONDS)
                save(history)
                if network.leave_own_ap():
                    print('Searching for saved stations while the camera access point is unused.', flush=True)
                    scan_for_station(network, history, save)
                else:
                    network.finish_checkpoint(history['probe'], restore=False)
                    history.pop('probe')
                    save(history)
                return
        save(history)
        return
    if condition == 'starting-ap':
        return
    history.pop('next_probe', None)
    if condition is None:
        history.pop('outage_since', None)
    else:
        # Include transitions between DHCP, association and disconnection.
        # A visible station with bad credentials must not starve the local AP.
        history.setdefault('outage_since', now)
    save(history)
    if condition == 'reconnecting':
        return
    if condition and now - history['outage_since'] >= AP_WAIT_SECONDS:
        offer_fallback(network, history, now, condition, save)
        return
    if (condition == 'disconnected' and now - history['outage_since'] >= GRACE_SECONDS
            and not network.profiles(now)):
        offer_fallback(network, history, now, condition, save)
        return
    check_station(network, history, now, condition, save)


def main():
    import dbus
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('interface')
    args = parser.parse_args()
    uuid_file = Path('/var/lib/indi-allsky-wifi-recovery') / args.interface / 'ap.uuid'
    try:
        ap_uuid = str(UUID(uuid_file.read_text().strip()))
    except FileNotFoundError:
        ap_uuid = None
    except ValueError:
        print('Invalid access-point UUID; keeping station recovery active.', flush=True)
        ap_uuid = None
    directory = Path(os.environ['RUNTIME_DIRECTORY'])
    state = directory / 'state.json'

    def save(history):
        if not (set(history) - {'attempts'}) and not history.get('attempts') and not state.exists():
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
            network = NetworkManager(args.interface, ap_uuid)
            check(network, history, int(boottime()), save)
        except dbus.DBusException as error:
            # NM may stop, or a scan result may disappear during enumeration.
            # Never expose connection names, access points or credentials in our log.
            print('NetworkManager request unavailable (' + str(error.get_dbus_name()) + ').', flush=True)
        except ValueError as error:
            print(str(error), flush=True)


if __name__ == '__main__':
    main()
