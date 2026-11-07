# Wi-Fi recovery and the camera's fallback access point

A mobile camera can keep recording when its router disappears. This optional NetworkManager timer first gives the Pi time to rejoin a saved Wi-Fi network. If it cannot connect, it starts the camera's own Wi-Fi access point (AP). A Mac, iPhone or iPad can then reach the camera directly.

## Install

On Debian or Raspberry Pi OS the helper requires NetworkManager, systemd, `python3-dbus`, `iw` and `dnsmasq-base`. NetworkManager uses dnsmasq to give clients an address on the hotspot. The wireless adapter must support AP mode. Run these commands from the source checkout and replace `wlan0` if necessary.

```sh
nmcli -g WIFI-PROPERTIES.AP device show wlan0
sudo bash misc/setup_wifi_recovery.sh install wlan0
systemctl list-timers indi-allsky-wifi-recovery@wlan0.timer
```

If there is one recognizable indi-allsky hotspot already configured for this adapter, the installer adopts it and preserves its SSID, password and IP address. To choose explicitly, for example when there are several profiles, find the existing hotspot's UUID and supply it as the last argument:

```sh
nmcli -f NAME,UUID,TYPE connection show
sudo bash misc/setup_wifi_recovery.sh install wlan0 EXISTING-HOTSPOT-UUID
```

An adopted Wi-Fi profile must use AP mode on this adapter, WPA2-PSK with CCMP, and shared IPv4 at `10.42.0.1/24`. The original profile and the settings in it stay available. Only its autoconnect setting is handed to the timer. When no AP profile exists, the installer creates a dedicated 2.4 GHz profile with a unique SSID and a randomly generated password. Reinstalling retains its credentials. The installer can run over the current station's SSH connection. It applies the per-interface power saving setting without changing the current association.

## Connect from a Mac, iPhone or iPad

In Wi-Fi settings, join the camera hotspot with its usual password. If it was newly provisioned, view its SSID and password privately on the Pi. This command deliberately displays the credential; keep its output out of shared logs or screenshots.

```sh
sudo bash misc/setup_wifi_recovery.sh credentials wlan0
```

Open [the camera](https://10.42.0.1/indi-allsky/) or [the companion](https://10.42.0.1/indi-allsky/companion) in the browser. If the Pi's hostname is `allsky` and Bonjour is enabled, [allsky.local](https://allsky.local/indi-allsky/) also works. The direct address works on the hotspot independently of name resolution. macOS and iOS may report that this Wi-Fi has no internet access. Stay connected to use the local camera. To reach the camera from a regular LAN, use its Bonjour hostname or its address on that LAN.

## How the timer chooses a network

* The first check runs about 20 seconds after boot and subsequent checks run about once a minute. With no visible saved network, expect the AP about two to three minutes after disconnection. If the Pi keeps trying a visible network or waiting for an address, it allows about five minutes from the first observed outage before requesting the AP, plus the next timer tick and radio startup time.
* A station profile must allow autoconnect and match a recently seen router. Eligible stations are ordered by NetworkManager's priority and last use. The helper requests limited scans or retries while disconnected. A deliberate radio-off, manual disconnect or a healthy local network without internet does not trigger fallback.
* On a single radio, checking for a returning home network can require leaving AP mode. When the hotspot has no associated clients, the helper can search after about ten minutes. If no saved network is visible, the hotspot normally returns after about 16 seconds plus the radio's switching time. A 30-second NetworkManager checkpoint protects the return if the helper stops during this search. If a station connection starts, the helper allows up to three minutes for association and DHCP. Disconnect the Mac or iPad from the hotspot to allow unattended searches. The capture and UPS services keep running independently of these Wi-Fi changes.
* An unresponsive IP negotiation or driver can also affect connectivity. A connected station with no upstream internet is still valid. NetworkManager's [DHCP timeout](https://networkmanager.dev/docs/api/latest/settings-ipv4.html) and [autoconnect retry settings](https://networkmanager.dev/docs/api/latest/settings-connection.html) determine how long a station attempt can take.

Use `journalctl -u indi-allsky-wifi-recovery@wlan0.service --since today --no-pager` to inspect activity. The timer does not log Wi-Fi credentials.

## Remove

```sh
sudo bash misc/setup_wifi_recovery.sh remove wlan0
```

Removal restores the previous autoconnect setting for an adopted AP. A dedicated profile created by this installer is removed. Use a station connection when removing a dedicated AP that is in use. The previous station power setting is restored from the root-only record under `/var/lib/indi-allsky-wifi-recovery/`.

The project also provides the [general NetworkManager hotspot setup](Misc-Folder.md). When using automatic recovery, manage the fallback through this installer to keep its selected profile and return-to-station policy together.
