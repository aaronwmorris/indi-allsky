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
PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -c "import PyIndi, flask, astropy, cv2, cryptography, dbus, systemd, rawpy, scipy; from indi_allsky.wsgi import application; assert application is not None; print('All core modules and Flask WSGI application verified successfully!')"

echo "============================================================"
echo "=== 3. Testing Database & User Provisioning ==="
echo "============================================================"
test -f /var/lib/indi-allsky/indi-allsky.sqlite
/var/lib/indi-allsky/venv/bin/python3 -c "import sqlite3; conn = sqlite3.connect('/var/lib/indi-allsky/indi-allsky.sqlite'); rows = conn.cursor().execute('SELECT username FROM user').fetchall(); print('Provisioned database users:', rows); assert any(r[0] == 'admin' for r in rows)"
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
