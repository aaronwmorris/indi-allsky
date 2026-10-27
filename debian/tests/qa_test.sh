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

DISTRO=""
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
fi

DEB_FILES=()
if [ -n "$DISTRO" ]; then
    for deb in /work/*+"${DISTRO}"*.deb; do
        [ -f "$deb" ] && DEB_FILES+=("$deb")
    done
fi

if [ ${#DEB_FILES[@]} -eq 0 ]; then
    # Check if packages exist for a different distribution
    OTHER_DEBS=$(ls /work/*+*.deb 2>/dev/null || true)
    if [ -n "$OTHER_DEBS" ]; then
        echo "ERROR: Target distribution is '${DISTRO}', but the .deb packages in /work/ are built for a different distribution:" >&2
        echo "$OTHER_DEBS" >&2
        echo "Please test using the distribution container that matches the packages (or build packages for '${DISTRO}')." >&2
        exit 1
    fi
    for deb in /work/*.deb; do
        [ -f "$deb" ] && DEB_FILES+=("$deb")
    done
fi

if [ ${#DEB_FILES[@]} -eq 0 ]; then
    echo "ERROR: No .deb packages found in /work to install." >&2
    exit 1
fi

apt-get install -y "${DEB_FILES[@]}"

echo "============================================================"
echo "=== 2. Testing Bundled Virtualenv & Extensions ==="
echo "============================================================"
PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -c "
import PyIndi, flask, astropy, cv2, cryptography, dbus, systemd, rawpy, scipy, boto3, google.cloud.storage, adafruit_bme280, adafruit_bmp280, adafruit_ina219
from indi_allsky.wsgi import application
from indi_allsky.system_profile import get_system_hardware_profile
assert application is not None
profile = get_system_hardware_profile()
assert profile.tier in (1, 2, 3, 4), f'Invalid hardware tier: {profile.tier}'
print(f'All core, cloud, hardware sensor modules, Flask WSGI application, and Tier {profile.tier} ({profile.tier_name}) profile verified successfully!')
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

# Verify auto-tuned hardware profile note and tier parameters
tuned_rows = conn.cursor().execute(\"SELECT note FROM config WHERE note LIKE '%Tuned for Tier%'\").fetchall()
assert len(tuned_rows) > 0, 'Hardware profile tuning record missing from database config history'
assert 'TIMELAPSE_SCALE' in cfg, 'TIMELAPSE_SCALE missing from bootstrapped configuration'

print('Database verified: Admin user provisioned, coordinates verified (-34.9285, 138.6007, 50m), and hardware profile applied!')
"

echo "============================================================"
echo "=== 4. Testing System Configuration & Control Utility ==="
echo "============================================================"
test -f /etc/indi-allsky/flask.json
echo "Configuration file /etc/indi-allsky/flask.json is present!"

# Verify indi-allsky-ctl profile CLI execution against live configuration
/usr/bin/indi-allsky-ctl profile
echo "Control utility 'indi-allsky-ctl profile' executed successfully!"

echo "============================================================"
echo "=== 5. Testing Non-Interactive Package Upgrade / Reinstall ==="
echo "============================================================"
# Verify that upgrading/reinstalling packages with -y automatically reuses configuration without prompting
apt-get install --reinstall -y "${DEB_FILES[@]}"
test -f /etc/indi-allsky/flask.json
echo "Non-interactive package reinstall/upgrade passed without prompts!"

echo "============================================================"
echo "=== 6. Testing Debconf Reconfiguration ==="
echo "============================================================"
dpkg-reconfigure -f noninteractive indi-allsky
echo "Debconf reconfiguration passed!"

echo "============================================================"
echo "=== 7. Testing Package Purge ==="
echo "============================================================"
apt-get purge -y indi-allsky
test ! -d /var/lib/indi-allsky
test ! -d /etc/indi-allsky
echo "Package purge verified successfully!"

echo "============================================================"
echo "=== All Automated .deb QA Probes Passed Successfully! ==="
echo "============================================================"
