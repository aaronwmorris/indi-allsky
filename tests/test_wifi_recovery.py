"""Simulate NetworkManager's device, scan and profile state without a Wi-Fi radio."""
import pytest

from misc import wifi_recovery as recovery


class Network(recovery.NetworkManager):
    def __init__(self):
        self.device = 'wlan0'
        self.nm = dict(NetworkingEnabled=True, WirelessEnabled=True, WirelessHardwareEnabled=True)
        self.dev = dict(DeviceType=2, Managed=True, Autoconnect=True, State=30, StateReason=(30,0),
                        ActiveConnection='/', AvailableConnections=[])
        self.radio = dict(Mode=2, AccessPoints=[], ActiveAccessPoint='/known-ap', LastScan=-1)
        self.no_carrier = False
        self.saved = {}
        self.points = {}
        self.actions = []
        self.history = {}
        self.last_saved = {}

    def properties(self, path, interface):
        if path == recovery.NM_PATH:
            return self.nm
        if path == self.device:
            return self.dev if interface == recovery.DEVICE else self.radio
        return self.points[path]

    def settings(self, profile):
        return self.saved[profile]

    def carrier_missing(self):
        return self.no_carrier

    def profile(self, path, ssid, *, enabled=True, mode='infrastructure', priority=0, timestamp=0):
        self.dev['AvailableConnections'].append(path)
        self.saved[path] = {'connection': {'type':'802-11-wireless', 'autoconnect':enabled,
                                           'autoconnect-priority':priority,'timestamp':timestamp},
                            '802-11-wireless': {'mode':mode, 'ssid':ssid}}

    def ap(self, path, ssid, seen):
        self.radio['AccessPoints'] = list(set(self.radio['AccessPoints']) | {path})
        self.points[path] = dict(Mode=2, Ssid=ssid, LastSeen=seen)

    def activate(self, profile):
        assert self.last_saved['attempts'][-1] == self.now
        self.actions.append(('activate',profile))

    def request_scan(self):
        assert self.last_saved['scan'] == self.now
        self.actions.append(('scan',self.now))

    def save(self, history):
        self.last_saved = dict(history, attempts=list(history['attempts']))

    def tick(self, now):
        self.now = now
        recovery.check(self, self.history, now, self.save)


def test_router_unplugged_and_returns_even_at_another_access_point():
    nm=Network()
    nm.profile('home-profile',b'home')
    nm.ap('old-access-point',b'home',0)
    nm.dev.update(State=100,ActiveConnection='/active')
    nm.tick(0)
    nm.dev.update(State=30,ActiveConnection='/')
    # A cached old AP does not justify reconnecting after the router is unplugged.
    for now in range(60,1261,60):
        nm.tick(now)
    assert not [a for a in nm.actions if a[0]=='activate']
    scans=[t for action,t in nm.actions if action=='scan']
    assert scans and all(b-a >= 300 for a,b in zip(scans,scans[1:]))

    nm.ap('new-access-point',b'home',1320)
    nm.tick(1320)
    assert nm.actions[-1] == ('activate','home-profile')
    nm.dev.update(State=100,ActiveConnection='/restored')
    for now in (1380,2000,3000):
        nm.tick(now)
    assert [a for a in nm.actions if a[0]=='activate'] == [('activate','home-profile')]


def test_roaming_and_mobile_profile_keep_native_selection():
    nm=Network()
    nm.profile('home',b'home',priority=100)
    nm.profile('mobile',b'mobile',priority=5)
    nm.profile('mobile-recent',b'mobile',priority=5,timestamp=20)
    nm.profile('hotspot',b'mobile',mode='ap',priority=110)
    nm.profile('manual',b'mobile',enabled=False,priority=200)
    nm.ap('mobile-ap',b'mobile',140)
    nm.ap('unconfigured-open',b'unconfigured',140)
    nm.tick(20); nm.tick(140)
    assert nm.actions == [('activate','mobile-recent')]


@pytest.mark.parametrize('property,value',[
    ('State',100),('State',40),('State',50),('State',60),('State',70),('State',120),
    ('Managed',False),('Autoconnect',False),('DeviceType',1),('ActiveConnection','/active'),
    ('StateReason',(30,39)),('Mode',3),('NetworkingEnabled',False),('WirelessEnabled',False),
    ('WirelessHardwareEnabled',False),
])
def test_never_touches_working_connecting_disabled_or_intentionally_offline_device(property,value):
    nm=Network()
    nm.profile('saved',b'example');nm.ap('currently-visible',b'example',240)
    for values in (nm.dev,nm.nm,nm.radio):
        if property in values:
            values[property]=value
    nm.tick(60);nm.tick(240)
    assert nm.actions == []


def test_rate_limits_are_shared_across_profiles_and_survive_repeated_failures():
    nm=Network()
    nm.profile('saved',b'example')
    outcomes=[]
    for now in (0,119,120,121,300,419,420,719,720,1020,2000,3719,3720):
        nm.ap('seen',b'example',now)
        count=len(nm.actions)
        nm.tick(now)
        if len(nm.actions)>count:outcomes.append(now)
    assert outcomes == [120,420,720,3720]


def test_nm_already_started_connecting_during_discovery():
    nm=Network();nm.tick(0)
    def profiles(now):
        nm.dev['State']=50
        return ['saved']
    nm.profiles=profiles
    nm.tick(180)
    assert nm.actions == []


def test_normal_scanning_is_not_duplicated_and_never_seen_aps_are_ignored():
    nm=Network()
    nm.profile('saved',b'example')
    nm.ap('unseen',b'example',-1)
    nm.radio['LastScan']=119000
    nm.tick(0);nm.tick(120)
    assert nm.actions==[]
    assert nm.profiles(30)==[]


def test_failed_activation_still_consumes_budget():
    nm=Network();nm.profile('saved',b'example');nm.ap('seen',b'example',120)
    nm.tick(0)
    def fail(profile):
        raise RuntimeError('rejected')
    nm.activate=fail
    with pytest.raises(RuntimeError,match='rejected'):
        nm.tick(120)
    assert nm.last_saved['attempts']==[120]
    nm.tick(180)


@pytest.mark.parametrize('state,message', [(70, 'IP configuration'), (50, 'connection activation')])
def test_persistent_activation_is_reported_once_without_interrupting_it(capsys, state, message):
    nm = Network()
    nm.dev.update(State=state, ActiveConnection='/pending')
    for now in (0, 120, 599):
        nm.tick(now)
    assert capsys.readouterr().out == ''
    for now in (600, 660, 1800):
        nm.tick(now)
    assert capsys.readouterr().out.count(message) == 1
    assert nm.actions == []


@pytest.mark.parametrize('active_ap,carrier_missing', [('/known-ap',True),('/',False)])
def test_one_ambiguous_link_indicator_is_insufficient(active_ap, carrier_missing):
    nm = Network()
    nm.dev.update(State=100, ActiveConnection='/active')
    nm.radio['ActiveAccessPoint'] = active_ap
    nm.no_carrier = carrier_missing
    nm.tick(0)
    nm.tick(900)
    assert nm.actions == []


def test_active_without_both_ap_and_carrier_gets_only_a_scan(capsys):
    nm = Network()
    nm.dev.update(State=100, ActiveConnection='/active')
    nm.radio['ActiveAccessPoint'] = '/'
    nm.no_carrier = True
    for now in (0, 540, 600, 660, 900):
        nm.tick(now)
    assert nm.actions == [('scan',600),('scan',900)]
    assert capsys.readouterr().out.count('without an access point or kernel carrier') == 1
    nm.radio['ActiveAccessPoint'] = '/restored'
    nm.no_carrier = False
    nm.tick(1500)
    assert nm.actions == [('scan',600),('scan',900)]


class FallbackNetwork(Network):
    """NetworkManager checkpoint and radio state, preserving the real condition() logic."""
    ap_uuid = '23421417-e910-4a73-a680-247bbf1d2703'
    owner = ':1.2'

    def __init__(self):
        super().__init__()
        self.profile('/ap', b'Allsky', mode='ap', enabled=False)
        self.profile('/home', b'Home')
        self.points['/active-ap'] = dict(Uuid=self.ap_uuid, Connection='/ap')
        self.points['/active-station'] = dict(Uuid='another-uuid', Connection='/home')
        self.clients = False
        self.checkpoints = set()
        self.extended = []
        self.scan_at = None
        self.scan_delay = 4
        self.on_wait = None

    def tick(self, now):
        from unittest.mock import patch
        with patch.object(recovery, 'boottime', lambda: self.now), patch.object(recovery.time, 'sleep', self.wait):
            super().tick(now)

    def wait(self, seconds):
        self.now += seconds
        if self.on_wait:
            self.on_wait(self.now)
        if self.scan_at is not None and self.now >= self.scan_at + self.scan_delay:
            self.radio['LastScan'] = self.now * 1000

    def request_probe_scan(self):
        self.scan_at = self.now
        self.request_scan()

    def allow_dhcp(self, probe):
        assert probe['checkpoint'] in self.checkpoints
        self.extended.append(self.now)

    def fallback_profile(self):
        return '/ap'

    def activate(self, profile):
        self.actions.append(('activate', profile))
        if profile == '/ap':
            self.enter_ap()
        else:
            self.dev.update(State=50, StateReason=(50, 0), ActiveConnection='/active-station')
            self.radio.update(Mode=2)

    def enter_ap(self):
        self.dev.update(State=100, StateReason=(100, 0), ActiveConnection='/active-ap')
        self.radio.update(Mode=3)

    def ap_idle(self):
        return not self.clients

    def checkpoint(self):
        path = '/checkpoint/1'
        self.checkpoints.add(path)
        return path

    def finish_checkpoint(self, probe, restore):
        path = probe['checkpoint']
        if path not in self.checkpoints or probe['owner'] != self.owner:
            return False
        self.checkpoints.remove(path)
        self.actions.append(('finish', restore))
        if restore:
            self.enter_ap()
        return True

    def leave_own_ap(self):
        if self.clients:
            return False
        self.actions.append(('leave', self.now))
        self.dev.update(State=30, StateReason=(30, recovery.USER_REQUESTED), ActiveConnection='/')
        self.radio.update(Mode=2)
        return True

    def request_scan(self):
        self.actions.append(('scan', self.now))


def test_no_router_offers_hotspot_then_restores_it_after_unsuccessful_station_probe():
    nm = FallbackNetwork()
    nm.tick(0)
    nm.tick(recovery.GRACE_SECONDS - 1)
    assert nm.actions == []
    nm.tick(recovery.GRACE_SECONDS)
    assert nm.actions == [('activate', '/ap')]
    nm.tick(180)
    nm.tick(780)
    assert nm.actions[-3:] == [('leave', 780), ('scan', 780), ('finish', True)]
    assert not nm.extended and not nm.checkpoints
    assert nm.now == 784 and nm.condition() == 'fallback-ap'
    nm.tick(1020)
    assert nm.actions.count(('activate', '/ap')) == 1


def test_oscillating_dhcp_and_auth_states_cannot_starve_the_fallback():
    nm = FallbackNetwork()
    nm.ap('visible', b'Home', 60)
    for t, state in [(0, 50), (60, 70), (120, 120), (180, 110), (240, 30), (300, 70)]:
        nm.dev.update(State=state, ActiveConnection='/active-station' if state != 30 else '/')
        nm.ap('visible', b'Home', t)
        nm.tick(t)
    assert nm.actions[-1] == ('activate', '/ap')
    assert nm.condition() == 'fallback-ap'


def test_return_to_router_after_bounded_probe_and_commit_checkpoint():
    nm = FallbackNetwork()
    nm.enter_ap()
    nm.on_wait = lambda now: nm.ap('router', b'Home', now)
    nm.tick(5); nm.tick(605)
    assert nm.extended == [609]
    assert nm.actions[-1] == ('activate', '/home')
    nm.dev.update(State=100, ActiveConnection='/active-station')
    nm.tick(785)
    assert nm.actions[-1] == ('finish', False)
    assert not nm.checkpoints and 'probe' not in nm.history
    nm.tick(2000)
    assert nm.actions.count(('leave', 605)) == 1


def test_active_clients_keep_their_session():
    nm = FallbackNetwork()
    nm.enter_ap(); nm.clients = True
    nm.tick(0); nm.tick(600); nm.tick(1800)
    assert nm.actions == []
    nm.clients = False
    nm.tick(1860)
    assert nm.actions == [('leave', 1860), ('scan', 1860), ('finish', True)]


def test_client_joins_immediately_before_deactivation():
    nm = FallbackNetwork()
    nm.enter_ap(); nm.tick(0)
    create = nm.checkpoint

    def checkpoint():
        nm.clients = True
        return create()

    nm.checkpoint = checkpoint
    nm.tick(600)
    assert nm.actions == [('finish', False)]
    assert not nm.checkpoints and 'probe' not in nm.history
    assert nm.condition() == 'fallback-ap'


@pytest.mark.parametrize('protect', ['off', 'unmanaged', 'disconnect', 'other-ap'])
def test_no_hotspot_when_user_disabled_wifi_or_owns_the_connection(protect):
    nm = FallbackNetwork()
    nm.tick(0)
    if protect == 'off':
        nm.nm['WirelessEnabled'] = False
    elif protect == 'unmanaged':
        nm.dev['Managed'] = False
    elif protect == 'disconnect':
        nm.dev['Autoconnect'] = False
    else:
        nm.profile('/foreign', b'Other', mode='ap')
        nm.points['/other-active'] = dict(Uuid='other', Connection='/foreign')
        nm.dev.update(ActiveConnection='/other-active', State=70)
    nm.tick(600)
    assert nm.actions == []


def test_checkpoint_creation_failure_preserves_working_ap():
    nm = FallbackNetwork()
    nm.enter_ap(); nm.tick(0)
    nm.checkpoint = lambda: (_ for _ in ()).throw(RuntimeError('checkpoint conflict'))
    with pytest.raises(RuntimeError, match='conflict'):
        nm.tick(600)
    assert 'probe' not in nm.history and nm.actions == []
    assert nm.condition() == 'fallback-ap'


def test_missing_checkpoint_restores_owned_ap_after_timeout():
    nm = FallbackNetwork()
    nm.on_wait = lambda now: nm.ap('router', b'Home', now)
    nm.enter_ap(); nm.tick(0); nm.tick(600)
    nm.checkpoints.clear()  # lost e.g. during NetworkManager restart
    nm.tick(786)
    assert nm.actions[-1] == ('activate', '/ap')
    assert nm.condition() == 'fallback-ap' and 'probe' not in nm.history


def test_checkpoint_dbus_error_is_retried_without_another_disconnect():
    nm = FallbackNetwork()
    nm.on_wait = lambda now: nm.ap('router', b'Home', now)
    nm.enter_ap(); nm.tick(0); nm.tick(600)
    original = nm.finish_checkpoint

    def failed(*args, **kwargs):
        raise RuntimeError('NM busy')

    nm.finish_checkpoint = failed
    with pytest.raises(RuntimeError, match='NM busy'):
        nm.tick(786)
    assert nm.checkpoints and 'probe' in nm.history
    nm.finish_checkpoint = original
    nm.tick(840)
    assert nm.actions[-1] == ('finish', True)
    assert nm.condition() == 'fallback-ap'


def test_wifi_disabled_during_probe_cancels_rollback():
    nm = FallbackNetwork()
    nm.on_wait = lambda now: nm.ap('router', b'Home', now)
    nm.enter_ap(); nm.tick(0); nm.tick(600)
    nm.nm['WirelessEnabled'] = False
    nm.tick(660); nm.tick(900)
    assert nm.actions[-1] == ('finish', False)
    assert 'probe' not in nm.history and not nm.checkpoints


@pytest.mark.parametrize('result,output,expected', [(0, b'', True), (0, b'Station aa\n', False), (1, b'', False)])
def test_only_successful_empty_station_table_allows_a_probe(monkeypatch, result, output, expected):
    from types import SimpleNamespace
    monkeypatch.setattr(recovery.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=result, stdout=output))
    nm = object.__new__(recovery.NetworkManager)
    nm.interface = 'wlan0'
    assert nm.ap_idle() == expected


def test_other_wifi_with_ap_mode_is_not_a_station_candidate():
    nm = FallbackNetwork()
    nm.profile('/asiair', b'ASIAIR-AP', mode='infrastructure')
    nm.ap('asiair-radio', b'ASIAIR-AP', 120)
    nm.tick(0); nm.tick(120)
    assert nm.actions[-1] == ('activate', '/asiair')


@pytest.mark.parametrize('key_mgmt,proto,accepted', [
    ('wpa-psk', ['rsn'], True), ('wpa-psk', [], True), ('wpa-psk', ['wpa'], False),
    ('none', [], False), (None, [], False),
])
def test_only_installed_wpa_hotspot_can_be_activated(key_mgmt, proto, accepted):
    from types import SimpleNamespace
    nm = FallbackNetwork()
    nm.interface = 'wlan0'
    nm.saved['/ap']['connection']['uuid'] = nm.ap_uuid
    nm.saved['/ap']['ipv4'] = {'method':'shared'}
    if key_mgmt is not None:
        nm.saved['/ap']['802-11-wireless-security'] = {'key-mgmt':key_mgmt, 'proto':proto}
    nm.object = lambda path: SimpleNamespace(GetConnectionByUuid=lambda uuid: '/ap')
    nm.dbus = SimpleNamespace(Interface=lambda obj, iface: obj)
    if accepted:
        assert recovery.NetworkManager.fallback_profile(nm) == '/ap'
    else:
        with pytest.raises(ValueError, match='security'):
            recovery.NetworkManager.fallback_profile(nm)


def test_hotspot_changed_during_search_is_not_activated_or_rolled_back():
    nm = FallbackNetwork()
    nm.on_wait = lambda now: nm.ap('router', b'Home', now)
    nm.enter_ap(); nm.tick(0); nm.tick(600)
    nm.fallback_profile = lambda: (_ for _ in ()).throw(ValueError('insecure'))
    with pytest.raises(ValueError):
        nm.tick(786)
    assert nm.actions[-1] == ('finish', False)
    assert not nm.checkpoints


def test_pending_checkpoint_destroy_failure_retries_after_station_is_healthy():
    nm = FallbackNetwork()
    nm.on_wait = lambda now: nm.ap('router', b'Home', now)
    nm.enter_ap(); nm.tick(0); nm.tick(600)
    nm.dev.update(State=100, StateReason=(100, 0), ActiveConnection='/active-station')
    nm.radio.update(Mode=2)
    finish = nm.finish_checkpoint
    nm.finish_checkpoint = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('destroy failed'))
    with pytest.raises(RuntimeError):
        nm.tick(660)
    assert nm.checkpoints and nm.dev['ActiveConnection'] == '/active-station'
    nm.finish_checkpoint = finish
    nm.tick(720)
    assert nm.actions[-1] == ('finish', False)
    assert not nm.checkpoints


def test_scan_that_never_completes_restores_ap_after_sixteen_seconds():
    nm = FallbackNetwork()
    nm.scan_delay = 300
    nm.enter_ap(); nm.tick(0); nm.tick(600)
    assert nm.actions == [('leave', 600), ('scan', 600), ('finish', True)]
    assert nm.now == 616 and not nm.extended and nm.condition() == 'fallback-ap'


def test_new_scan_does_not_activate_a_cached_router_that_already_left():
    nm = FallbackNetwork()
    nm.ap('router', b'Home', 599)
    nm.enter_ap(); nm.tick(0); nm.tick(600)
    assert nm.actions == [('leave', 600), ('scan', 600), ('finish', True)]
    assert nm.now == 604 and not nm.extended


def test_native_station_association_gets_dhcp_time_without_duplicate_activation():
    nm = FallbackNetwork()

    def native_connect(now):
        nm.dev.update(State=70, StateReason=(70, 0), ActiveConnection='/active-station')
        nm.radio.update(Mode=2)

    nm.on_wait = native_connect
    nm.enter_ap(); nm.tick(0); nm.tick(600)
    assert nm.extended == [602]
    assert nm.history['probe']['until'] == 782
    assert not [action for action in nm.actions if action[0] == 'activate']
    nm.tick(700)
    assert nm.checkpoints
    nm.dev.update(State=100)
    nm.tick(800)
    assert nm.actions[-1] == ('finish', False)


def test_user_requested_transition_of_own_deactivation_is_temporary():
    nm = FallbackNetwork()
    nm.enter_ap()
    nm.dev.update(State=110, StateReason=(110, recovery.USER_REQUESTED))
    assert nm.condition(probing=True) == 'probe-transition'
    nm.dev['Autoconnect'] = False
    assert nm.condition(probing=True) is None


def test_checkpoint_timeout_is_short_until_actual_station_activation():
    from types import SimpleNamespace
    from unittest.mock import Mock
    manager = Mock()
    manager.CheckpointCreate.return_value = '/checkpoint'
    nm = SimpleNamespace(manager=manager, device='/device')
    assert recovery.NetworkManager.checkpoint(nm) == '/checkpoint'
    manager.CheckpointCreate.assert_called_once_with(['/device'], 30, 0, timeout=4)
    recovery.NetworkManager.allow_dhcp(nm, {'checkpoint':'/checkpoint'})
    manager.CheckpointAdjustRollbackTimeout.assert_called_once_with('/checkpoint', 270, timeout=4)
