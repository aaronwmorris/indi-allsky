#!/bin/bash
# Optional NetworkManager station recovery. Run independently of setup.sh.
set -euo pipefail
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

action=${1:-install}
interface=${2:-wlan0}
if [[ $EUID -ne 0 || $# -gt 2 || ! $interface =~ ^[A-Za-z0-9_.-]{1,15}$ || $interface == -* ||
      ( $action != install && $action != remove ) ]]; then
    echo 'Usage: sudo bash misc/setup_wifi_recovery.sh {install|remove} [wlan0]' >&2
    exit 2
fi
tree=$(cd "$(dirname "$0")/.." && pwd)
conf="/etc/NetworkManager/conf.d/90-indi-allsky-wifi-${interface}.conf"
state_root=/var/lib/indi-allsky-wifi-recovery
history="${state_root}/${interface}"
lib=/usr/local/lib/indi-allsky
units=/etc/systemd/system
timer="indi-allsky-wifi-recovery@${interface}.timer"
marker='# Managed by indi-allsky setup_wifi_recovery.sh'
for directory in "$state_root" "$history"; do
    if [[ -L $directory || ( -e $directory && ! -d $directory ) ]]; then
        echo 'Unsafe Wi-Fi recovery state directory; refusing to proceed.' >&2; exit 1
    fi
    if [[ -d $directory ]] && { [[ $(stat -c %u "$directory") != 0 ]] ||
                                    (( 8#$(stat -c %a "$directory") & 8#022 )); }; then
        echo 'Wi-Fi recovery state must be root-owned and not writable by other accounts.' >&2; exit 1
    fi
done
if [[ -f $conf ]] && ! grep -Fqx "$marker" "$conf"; then
    echo 'The target NetworkManager drop-in already exists and is not managed by this installer.' >&2
    exit 1
fi

active_uuid() {
    nmcli -t -f UUID,TYPE,DEVICE connection show --active |
        awk -F: -v device="$interface" '$3 == device && ($2 == "wifi" || $2 == "802-11-wireless") && !found { print $1; found=1 }'
}

profile_power() {
    local raw
    raw=$(nmcli -g 802-11-wireless.powersave connection show uuid "$1")
    case "${raw%% *}" in
        0|default|'') echo 0 ;;
        1|ignore) echo 1 ;;
        2|disable) echo 2 ;;
        3|enable) echo 3 ;;
        *) echo 'Unexpected NetworkManager power-save value.' >&2; return 1 ;;
    esac
}

if [[ $action == remove ]]; then
    if [[ -e $conf || -d $history ]]; then systemctl is-active --quiet NetworkManager.service; fi
    systemctl disable --now "$timer" 2>/dev/null || true
    systemctl stop "indi-allsky-wifi-recovery@${interface}.service" 2>/dev/null || true
    if [[ -e $conf ]]; then
        rm -- "$conf"
        nmcli general reload conf
    fi
    shopt -s nullglob
    for record in "$history"/*.previous; do
        [[ -f $record && ! -L $record ]] || exit 1
        uuid=${record##*/}; uuid=${uuid%.previous}
        read -r saved runtime < "$record"
        if nmcli connection show uuid "$uuid" >/dev/null 2>&1 && [[ $(profile_power "$uuid") == 2 ]]; then
            nmcli connection modify uuid "$uuid" 802-11-wireless.powersave "$saved"
            if [[ $runtime == on || $runtime == off ]] && [[ $(active_uuid) == "$uuid" ]]; then
                iw dev "$interface" set power_save "$runtime"
            fi
        fi
        rm -- "$record"
    done
    if [[ -d $history ]]; then rmdir -- "$history"; fi
    # The service templates and helper are shared with any other installed interface.
    dropins=(/etc/NetworkManager/conf.d/90-indi-allsky-wifi-*.conf)
    if (( ${#dropins[@]} == 0 )); then
        rm -f -- "$units/indi-allsky-wifi-recovery@.timer" "$units/indi-allsky-wifi-recovery@.service" "$lib/wifi_recovery.py"
        systemctl daemon-reload
        rmdir -- "$state_root" 2>/dev/null || true
    fi
    echo 'Wi-Fi recovery removed.'
    exit 0
fi

for bin in nmcli iw systemctl python3; do command -v "$bin" >/dev/null; done
/usr/bin/python3 -c 'import dbus'
systemctl is-active --quiet NetworkManager.service
if [[ $(nmcli -g GENERAL.TYPE device show "$interface") != wifi ]]; then
    echo 'Choose an existing NetworkManager Wi-Fi interface.' >&2
    exit 1
fi
install -d -m 0700 "$state_root" "$history"
uuid=$(active_uuid)
station=false
if [[ -n $uuid ]]; then
    mode=$(nmcli -g 802-11-wireless.mode connection show uuid "$uuid")
    if [[ $mode == infrastructure || -z $mode ]]; then
        station=true
        [[ ! -L "$history/$uuid.previous" ]] || exit 1
        if [[ ! -e "$history/$uuid.previous" ]]; then
            prior=$(profile_power "$uuid")
            runtime=$(iw dev "$interface" get power_save | awk '/Power save:/ {print $3}')
            printf '%s %s\n' "$prior" "${runtime:-unknown}" > "$history/$uuid.previous"
        fi
    fi
fi

install -d -m 0755 "$lib" /etc/NetworkManager/conf.d
install -m 0755 "$tree/misc/wifi_recovery.py" "$lib/wifi_recovery.py"
for kind in service timer; do
    install -m 0644 "$tree/service/indi-allsky-wifi-recovery@.$kind" "$units/indi-allsky-wifi-recovery@.$kind"
done
{
    echo "$marker"
    echo "[connection-indi-allsky-wifi-${interface}]"
    echo "match-device=interface-name:${interface}"
    echo 'wifi.powersave=2'
} > "$conf"
chmod 0644 "$conf"
nmcli general reload conf
if [[ $station == true ]] && [[ $(active_uuid) == "$uuid" ]]; then
    nmcli connection modify uuid "$uuid" 802-11-wireless.powersave 2
    # Apply only this radio setting immediately, without reactivating the connection.
    if [[ $(active_uuid) == "$uuid" ]] && ! iw dev "$interface" set power_save off; then
        echo 'The profile is saved; its power setting will take effect on the next association.' >&2
    fi
fi
systemctl daemon-reload
systemctl enable --now "$timer"
echo "Installed $timer. Inspect with: systemctl status $timer"
