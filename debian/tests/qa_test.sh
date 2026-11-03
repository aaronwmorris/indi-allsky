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
GUNICORN_ERROR_LOG_HANDLER=wsgi PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -c "
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
echo "=== 4. Testing Authenticated Web Routes & WSGI Server ==="
echo "============================================================"

# Verify unauthenticated and authenticated route rendering via Flask WSGI test client as indi-allsky user
su -s /bin/sh indi-allsky -c "GUNICORN_ERROR_LOG_HANDLER=wsgi PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -c '
import re, logging, logging.handlers
from indi_allsky.wsgi import application
assert application is not None

# Remove syslog handler if /dev/log is absent in container to prevent socket connection errors
allsky_logger = logging.getLogger(\"indi_allsky\")
allsky_logger.handlers = [h for h in allsky_logger.handlers if not isinstance(h, logging.handlers.SysLogHandler)]

with application.test_client() as client:
    # 1. Verify unauthenticated login route and static asset delivery
    res_login = client.get(\"/indi-allsky/login\")
    assert res_login.status_code == 200, f\"Expected 200 on /indi-allsky/login, got {res_login.status_code}\"
    login_html = res_login.get_data(as_text=True)

    res_css = client.get(\"/indi-allsky/static/css/dist.css\")
    assert res_css.status_code == 200, f\"Expected 200 on dist.css, got {res_css.status_code}\"
    assert len(res_css.data) > 1000, \"dist.css is empty or truncated\"

    # 2. Extract CSRF token from login form
    csrf_match = re.search(r\"name=[\x27\\\"]csrf_token[\x27\\\"][^>]*value=[\x27\\\"]([^\x27\\\"]+)[\x27\\\"]\", login_html) or \
                 re.search(r\"value=[\x27\\\"]([^\x27\\\"]+)[\x27\\\"][^>]*name=[\x27\\\"]csrf_token[\x27\\\"]\", login_html)
    assert csrf_match is not None, \"CSRF token missing from login page HTML\"
    csrf_token = csrf_match.group(1)

    # 3. Authenticate as preseeded admin user
    login_res = client.post(
        \"/indi-allsky/login\",
        json={
            \"USERNAME\": \"admin\",
            \"PASSWORD\": \"testpassword123\",
            \"NEXT\": \"\",
            \"csrf_token\": csrf_token,
        },
        headers={\"X-CSRFToken\": csrf_token},
    )
    assert login_res.status_code == 200, f\"Admin login failed with HTTP {login_res.status_code}: {login_res.get_data(as_text=True)}\"

    # 4. Authenticated web routes rendering sweep
    routes = [
        \"/indi-allsky/\",
        \"/indi-allsky/config\",
        \"/indi-allsky/system\",
        \"/indi-allsky/users\",
        \"/indi-allsky/sensor_panel\",
    ]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code == 200, f\"Route {route} failed with HTTP {resp.status_code}: {resp.get_data(as_text=True)[:300]}\"

print(\"All core authenticated web routes (/indi-allsky/, /config, /system, /users, /sensor_panel) rendered successfully!\")
'"

# Verify live Gunicorn WSGI HTTP server binding and serving requests on loopback
su -s /bin/sh indi-allsky -c "GUNICORN_ERROR_LOG_HANDLER=wsgi exec /var/lib/indi-allsky/venv/bin/gunicorn \
    --bind 127.0.0.1:8080 \
    --workers 1 \
    --timeout 15 \
    --access-logfile - \
    --error-logfile - \
    indi_allsky.wsgi:application" &
GUNICORN_PID=$!

/var/lib/indi-allsky/venv/bin/python3 -c "
import urllib.request, time

for _ in range(20):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080/indi-allsky/login', timeout=2) as resp:
            if resp.status == 200:
                print('Live Gunicorn WSGI server successfully served HTTP 200 on loopback!')
                break
    except Exception:
        time.sleep(0.5)
else:
    raise RuntimeError('Gunicorn WSGI server failed to respond within 10 seconds')
"
kill "$GUNICORN_PID" 2>/dev/null || true
wait "$GUNICORN_PID" 2>/dev/null || true
pkill -f gunicorn 2>/dev/null || true
echo "Live Gunicorn WSGI server smoke test verified successfully!"

echo "============================================================"
echo "=== 5. Testing System Configuration & CLI Utilities ==="
echo "============================================================"
test -f /etc/indi-allsky/flask.json
echo "Configuration file /etc/indi-allsky/flask.json is present!"

# Verify CLI utilities execution
/var/lib/indi-allsky/venv/bin/python3 /usr/share/indi-allsky/allsky.py --help > /dev/null
/var/lib/indi-allsky/venv/bin/python3 /usr/share/indi-allsky/config.py --help > /dev/null
echo "CLI utilities (--help) executed successfully!"

echo "============================================================"
echo "=== 6. Testing Non-Interactive Package Upgrade / Reinstall ==="
echo "============================================================"
# Verify that upgrading/reinstalling packages with -y automatically reuses configuration without prompting
apt-get install --reinstall -y "${DEB_FILES[@]}"
test -f /etc/indi-allsky/flask.json
echo "Non-interactive package reinstall/upgrade passed without prompts!"

echo "============================================================"
echo "=== 7. Testing Debconf Reconfiguration ==="
echo "============================================================"
dpkg-reconfigure -f noninteractive indi-allsky
echo "Debconf reconfiguration passed!"

echo "============================================================"
echo "=== 8. Testing Package Purge ==="
echo "============================================================"
apt-get purge -y indi-allsky
test ! -d /var/lib/indi-allsky
test ! -d /etc/indi-allsky
echo "Package purge verified successfully!"

echo "============================================================"
echo "=== All Automated .deb QA Probes Passed Successfully! ==="
echo "============================================================"
