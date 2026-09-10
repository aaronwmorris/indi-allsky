#!/bin/sh
set -e

# Detect primary IP address
HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$HOST_IP" ]; then
    HOST_IP=$(ip -4 addr show scope global 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1)
fi
if [ -z "$HOST_IP" ]; then
    HOST_IP=$(hostname -s 2>/dev/null || echo "localhost")
fi

HTTP_P="${HTTP_PORT:-80}"
HTTPS_P="${HTTPS_PORT:-443}"

SUMMARY_FILE="/var/lib/indi-allsky/.pending_summary"
mkdir -p /var/lib/indi-allsky
touch "$SUMMARY_FILE"
chmod 600 "$SUMMARY_FILE" 2>/dev/null || true
chown root:root "$SUMMARY_FILE" 2>/dev/null || true

cat <<EOF_SUM > "$SUMMARY_FILE"

================================================================================
                    indi-allsky Installation Complete!                         
================================================================================

 Web Interface:
EOF_SUM

if [ "$HTTPS_P" = "443" ]; then
    echo "   https://${HOST_IP}/indi-allsky/" >> "$SUMMARY_FILE"
else
    echo "   https://${HOST_IP}:${HTTPS_P}/indi-allsky/" >> "$SUMMARY_FILE"
fi
if [ "$HTTP_P" = "80" ]; then
    echo "   http://${HOST_IP}/indi-allsky/" >> "$SUMMARY_FILE"
else
    echo "   http://${HOST_IP}:${HTTP_P}/indi-allsky/" >> "$SUMMARY_FILE"
fi
echo "" >> "$SUMMARY_FILE"

if [ -n "$GENERATED_ADMIN_PASS" ]; then
    cat <<EOF_ADMIN >> "$SUMMARY_FILE"
 [!] Web Admin Credentials (Auto-Generated):
     Username: ${ADMIN_USER:-admin}
     Password: ${GENERATED_ADMIN_PASS}
     (Please log in and change this password immediately!)

EOF_ADMIN
fi

if [ -n "$GENERATED_MQTT_PASS" ]; then
    cat <<EOF_MQTT >> "$SUMMARY_FILE"
 [!] Mosquitto MQTT Credentials (Auto-Generated):
     Username: ${GENERATED_MQTT_USER:-indi-allsky}
     Password: ${GENERATED_MQTT_PASS}
     (To change: sudo mosquitto_passwd /etc/mosquitto/passwd ${GENERATED_MQTT_USER:-indi-allsky})

EOF_MQTT
fi


echo "================================================================================" >> "$SUMMARY_FILE"
echo "" >> "$SUMMARY_FILE"

# Check if running under APT (which will trigger DPkg::Post-Invoke).
# If running standalone via dpkg -i, print immediately.
GRANDPARENT_PID=$(ps -o ppid= -p $PPID 2>/dev/null | tr -d " " || echo "0")
RUNNING_UNDER_APT=0
if [ -f "/proc/$PPID/cmdline" ] && grep -q -s -E 'apt|apt-get|aptitude|synaptic' "/proc/$PPID/cmdline" 2>/dev/null; then
    RUNNING_UNDER_APT=1
elif [ "$GRANDPARENT_PID" -gt 0 ] 2>/dev/null && [ -f "/proc/$GRANDPARENT_PID/cmdline" ] && grep -q -s -E 'apt|apt-get|aptitude|synaptic' "/proc/$GRANDPARENT_PID/cmdline" 2>/dev/null; then
    RUNNING_UNDER_APT=1
fi

if [ "$RUNNING_UNDER_APT" = "0" ] && [ -f "$SUMMARY_FILE" ]; then
    cat "$SUMMARY_FILE"
    rm -f "$SUMMARY_FILE"
fi
