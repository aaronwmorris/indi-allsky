# Optional Wi-Fi recovery for mobile stations

On a Raspberry Pi running NetworkManager, this companion timer helps a saved Wi-Fi network reconnect when its access point returns. Image capture and the local web interface run independently of the timer. Install it only on stations where this behavior is wanted.

## Install from a source checkout

Debian / Raspberry Pi OS requires NetworkManager, systemd, `python3-dbus` and `iw`. Replace `wlan0` below if the Wi-Fi interface has another name. These read-only commands show device and radio status without displaying network names:

```sh
nmcli -t -f DEVICE,TYPE,STATE device status
iw dev wlan0 get power_save
```

Keep the current SSH session open and run from the checkout:

```sh
sudo bash misc/setup_wifi_recovery.sh install wlan0
systemctl status indi-allsky-wifi-recovery@wlan0.timer --no-pager
systemctl list-timers indi-allsky-wifi-recovery@wlan0.timer
iw dev wlan0 get power_save
```

The installer adds a NetworkManager power-saving default for this interface (`wifi.powersave=2`). Profiles using the default inherit it. An explicit value on a different profile is respected. For an active infrastructure profile the installer also persists the disabled setting and applies it directly to the radio with `iw`. It reloads only NetworkManager's configuration. The active connection stays up throughout. No call to `connection down/up`, global networking toggle or NetworkManager restart is needed to install or test it.

## When it intervenes

The timer first runs two minutes after boot and checks roughly once a minute. NetworkManager handles normal association, DHCP, roaming and profile changes itself. The check acts on a managed station interface only when the radio, networking and automatic connection are enabled, no connection is active and NetworkManager has reported the device disconnected for at least two minutes.

* An infrastructure profile must already exist, permit autoconnect, be available to NetworkManager and match an access point seen in the past 90 seconds. Among matches, profile autoconnect priority and last-used time determine the selection. NetworkManager chooses the access point; the helper stores no SSID, BSSID or credentials.
* When the router is absent there are no forced connection attempts. If NetworkManager's own scans have stopped for five minutes, the helper may request one broadcast scan, at most once every five minutes. A hidden network that never advertises its SSID remains the responsibility of NetworkManager's configured hidden-network discovery.
* An eligible but still disconnected interface gets at most one activation request per five minutes and three per rolling hour across all profiles. This includes rejected requests. The attempt budget survives individual checks and resets at boot.
* A connected station can keep taking images on a LAN with no internet. The helper performs no gateway pings, internet requests or DNS checks. It does not interrupt connected/connecting devices, access points, radio-off or user-disconnected devices. It does not reset NetworkManager, the interface, camera capture or the web server.
* If IP configuration or another connecting phase stays pending for ten minutes, it logs the condition once and leaves the existing activation alone. NetworkManager's [IPv4 DHCP timeout](https://networkmanager.dev/docs/api/latest/settings-ipv4.html) is normally about 45 seconds per transaction unless configured otherwise, including an explicitly infinite timeout. The [autoconnect retry count](https://networkmanager.dev/docs/api/latest/settings-connection.html) normally defaults to four attempts, with later automatic retries. These settings do not define a universal deadline for every connecting state.
* If NetworkManager reports an active station for ten minutes while it has no active access point **and** the kernel reports no carrier, it logs the mismatch and may request the same bounded scan when native scans have stopped. It never reactivates that connection. A still-associated but unreachable client, router, driver or IP route needs separate diagnosis.

To inspect activity:

```sh
journalctl -u indi-allsky-wifi-recovery@wlan0.service --since today --no-pager
```

To simulate router loss/return, absence of internet, changes between saved networks, manual disconnect and the retry budget without changing the live network:

```sh
python3 -m pytest -q tests/test_wifi_recovery.py
```

## Remove

```sh
sudo bash misc/setup_wifi_recovery.sh remove wlan0
```

This stops the optional checks and removes their NetworkManager drop-in. The installer records the previous Wi-Fi profile/radio power values under the private, root-owned `/var/lib/indi-allsky-wifi-recovery/`. The removal command restores the original power setting of the profile adjusted at installation if that profile still exists and the setting still has the installed value. It restores the previous live radio setting only when the same profile is active. Other existing profile choices stay intact.

The implementation uses NetworkManager's [device](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.html), [Wi-Fi device](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.Wireless.html) and [access-point](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.AccessPoint.html) D-Bus interfaces, [per-device defaults](https://networkmanager.dev/docs/api/latest/NetworkManager.conf.html) and [wireless profile settings](https://networkmanager.dev/docs/api/latest/settings-802-11-wireless.html).
