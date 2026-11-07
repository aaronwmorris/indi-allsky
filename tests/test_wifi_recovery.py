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
