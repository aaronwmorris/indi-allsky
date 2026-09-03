#!/bin/bash
set -euo pipefail

echo "============================================================"
echo "=== 1. Testing Preseeded Non-Interactive Package Install ==="
echo "============================================================"
debconf-set-selections <<EOF
indi-allsky indi-allsky/latitude string -34.9285
indi-allsky indi-allsky/longitude string 138.6007
indi-allsky indi-allsky/elevation string 50
indi-allsky indi-allsky/web_user string admin
indi-allsky indi-allsky/web_pass password testpassword123
indi-allsky indi-allsky/web_pass_confirm password testpassword123
EOF

apt-get update
apt-get install -y /work/*.deb

echo "============================================================"
echo "=== 2. Testing Bundled Virtualenv & Extensions ==="
echo "============================================================"
PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -c "
import PyIndi, flask, astropy, cv2, cryptography, dbus, systemd, rawpy, scipy, boto3, google.cloud.storage, adafruit_bme280, adafruit_bmp280, adafruit_ina219
from indi_allsky.wsgi import application
assert application is not None
print('All core, cloud, and hardware sensor modules and Flask WSGI application verified successfully!')
"

echo "============================================================"
echo "=== 3. Testing Database, Coordinates & Non-Root Access ==="
echo "============================================================"
test -f /var/lib/indi-allsky/indi-allsky.sqlite

# Verify non-root service user has write access to the database (prevents readonly database regressions)
su -s /bin/sh indi-allsky -c "/var/lib/indi-allsky/venv/bin/python3 -c '
import sqlite3
conn = sqlite3.connect(\"/var/lib/indi-allsky/indi-allsky.sqlite\")
cursor = conn.cursor()
cursor.execute(\"CREATE TABLE IF NOT EXISTS _qa_test (id INTEGER PRIMARY KEY, val TEXT);\")
cursor.execute(\"INSERT INTO _qa_test (val) VALUES (\x27test_write\x27);\")
conn.commit()
cursor.execute(\"DROP TABLE _qa_test;\")
conn.commit()
print(\"Non-root service user database write verified successfully!\")
'"

/var/lib/indi-allsky/venv/bin/python3 -c "
import sqlite3, json

conn = sqlite3.connect('/var/lib/indi-allsky/indi-allsky.sqlite')
# Verify users
users = [r[0] for r in conn.cursor().execute('SELECT username FROM user').fetchall()]
assert 'admin' in users, f'Admin user missing: {users}'

# Verify observatory latitude, longitude, and elevation from database config table
data_row = conn.cursor().execute('SELECT data FROM config ORDER BY id DESC LIMIT 1').fetchone()
assert data_row is not None, 'No config entry found in database'
cfg = json.loads(data_row[0])
assert abs(cfg.get('LOCATION_LATITUDE', 0) - (-34.9285)) < 1e-4, f'Latitude mismatch: {cfg.get(\"LOCATION_LATITUDE\")}'
assert abs(cfg.get('LOCATION_LONGITUDE', 0) - 138.6007) < 1e-4, f'Longitude mismatch: {cfg.get(\"LOCATION_LONGITUDE\")}'
assert int(cfg.get('LOCATION_ELEVATION', 0)) == 50, f'Elevation mismatch: {cfg.get(\"LOCATION_ELEVATION\")}'
print('Database verified: Admin user provisioned and observatory coordinates verified (-34.9285, 138.6007, 50m)!')
"

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
