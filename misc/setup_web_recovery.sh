#!/bin/bash
# Install the user-level observer that accompanies a source installation.
set -euo pipefail

action=${1:-install}
unit=${2:-gunicorn-indi-allsky}
port=${3:-443}
if [[ $EUID -eq 0 || $# -gt 3 || ! $unit =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ ||
      ! $port =~ ^[1-9][0-9]{0,4}$ || $port -gt 65535 ||
      ( $action != install && $action != remove ) ]]; then
    echo 'Run as the camera service user: setup_web_recovery.sh {install|remove} [Gunicorn unit basename] [local HTTPS port]' >&2
    exit 2
fi
tree=$(cd "$(dirname "$0")/.." && pwd)
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
lib="$HOME/.local/lib/indi-allsky"
name=indi-allsky-web-recovery
override="$units/$unit.service.d/50-indi-allsky-web-recovery.conf"
marker='# Managed by indi-allsky setup_web_recovery.sh'
if [[ -e $override ]] && ! grep -Fqx "$marker" "$override"; then
    echo "An existing unmanaged override uses $override" >&2
    exit 1
fi

if [[ $action == remove ]]; then
    systemctl --user disable --now "$name.timer" 2>/dev/null || true
    systemctl --user stop "$name.service" 2>/dev/null || true
    rm -f -- "$override" "$units/$name.timer" "$units/$name.service" "$lib/web_recovery.py"
    systemctl --user daemon-reload
    exit 0
fi
for suffix in service socket; do
    if [[ $(systemctl --user show "$unit.$suffix" -p LoadState --value) != loaded ]]; then
        echo "Expected a source installation with user unit $unit.$suffix." >&2
        exit 1
    fi
done
install -d -m 0755 "$lib" "$units" "$units/$unit.service.d"
install -m 0644 "$tree/misc/web_recovery.py" "$lib/web_recovery.py"
install -m 0644 "$tree/service/$name.timer" "$units/$name.timer"
sed -e "s/%GUNICORN_SERVICE_NAME%/$unit/g" -e "s/%HTTPS_PORT%/$port/g" \
    "$tree/service/$name.service" > "$units/$name.service.tmp"
mv -- "$units/$name.service.tmp" "$units/$name.service"
cat > "$override.tmp" <<EOF
$marker
[Unit]
StartLimitIntervalSec=15min
StartLimitBurst=3
[Service]
Restart=on-failure
RestartSec=15s
EOF
mv -- "$override.tmp" "$override"
systemctl --user daemon-reload
systemctl --user enable --now "$name.timer"
