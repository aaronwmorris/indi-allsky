#!/bin/bash
set -euo pipefail

echo "============================================================"
echo "=== 1. Testing Non-Interactive Package Installation ==="
echo "============================================================"
apt-get update
apt-get install -y /work/*.deb

echo "============================================================"
echo "=== 2. Testing Sandboxed Virtualenv & C-Extensions ==="
echo "============================================================"
/var/lib/indi-allsky/venv/bin/python3 -c "import pyindi_client, flask, astropy, cv2, cryptography, dbus, systemd, rawpy, scipy; print('All core Python and C-extension modules verified successfully!')"

echo "============================================================"
echo "=== 3. Testing Database & User Provisioning ==="
echo "============================================================"
test -f /var/lib/indi-allsky/indi-allsky.sqlite
sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite "SELECT username FROM user;" | grep -q "admin"
echo "Database verified and admin user provisioned!"

echo "============================================================"
echo "=== 4. Testing System Configuration ==="
echo "============================================================"
test -f /etc/indi-allsky/flask.json
echo "Configuration file /etc/indi-allsky/flask.json is present!"

echo "============================================================"
echo "=== 5. Testing Debconf Reconfiguration ==="
echo "============================================================"
dpkg-reconfigure -f noninteractive indi-allsky
echo "Debconf reconfiguration passed!"

echo "============================================================"
echo "=== 6. Testing Package Purge ==="
echo "============================================================"
apt-get purge -y indi-allsky
echo "============================================================"
echo "=== All Automated .deb QA Probes Passed Successfully! ==="
echo "============================================================"
