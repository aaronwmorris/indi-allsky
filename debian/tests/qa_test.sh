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
su -s /bin/sh indi-allsky -c "GUNICORN_ERROR_LOG_HANDLER=wsgi PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -" <<'PYEOF'
import re, json, logging, logging.handlers
from html.parser import HTMLParser
from indi_allsky.wsgi import application
from indi_allsky.flask.models import IndiAllSkyDbConfigTable
assert application is not None

# Remove syslog handler if /dev/log is absent in container to prevent socket connection errors
allsky_logger = logging.getLogger("indi_allsky")
allsky_logger.handlers = [h for h in allsky_logger.handlers if not isinstance(h, logging.handlers.SysLogHandler)]


class ConfigFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = {}
        self.checkboxes = {}
        self.selects = {}
        self.textareas = {}
        self._cur_select = None
        self._cur_options = []
        self._cur_selected = None
        self._cur_textarea = None
        self._textarea_buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        el_id = a.get("id") or a.get("name")
        if tag == "input" and el_id:
            t = a.get("type", "text").lower()
            if t == "checkbox":
                self.checkboxes[el_id] = "checked" in a
            elif t != "submit":
                self.inputs[el_id] = a.get("value", "")
        elif tag == "select" and el_id:
            self._cur_select = el_id
            self._cur_options = []
            self._cur_selected = None
        elif tag == "option" and self._cur_select is not None:
            val = a.get("value", "")
            self._cur_options.append(val)
            if "selected" in a:
                self._cur_selected = val
        elif tag == "textarea" and el_id:
            self._cur_textarea = el_id
            self._textarea_buf = []

    def handle_data(self, data):
        if self._cur_textarea is not None:
            self._textarea_buf.append(data)

    def handle_endtag(self, tag):
        if tag == "select" and self._cur_select is not None:
            if self._cur_selected is not None:
                self.selects[self._cur_select] = self._cur_selected
            elif self._cur_options:
                self.selects[self._cur_select] = self._cur_options[0]
            else:
                self.selects[self._cur_select] = ""
            self._cur_select = None
        elif tag == "textarea" and self._cur_textarea is not None:
            self.textareas[self._cur_textarea] = "".join(self._textarea_buf)
            self._cur_textarea = None


with application.test_client() as client:
    # 1. Verify unauthenticated access controls
    for protected_route in ["/indi-allsky/config", "/indi-allsky/users", "/indi-allsky/system"]:
        unauth_res = client.get(protected_route)
        assert unauth_res.status_code in (302, 401, 403), f"Unauthenticated GET {protected_route} returned {unauth_res.status_code}"
    unauth_post = client.post("/indi-allsky/ajax/config", json={})
    assert unauth_post.status_code in (302, 400, 401, 403), f"Unauthenticated POST /ajax/config returned {unauth_post.status_code}"

    # 2. Verify unauthenticated login route and packaged static/PWA asset delivery
    res_login = client.get("/indi-allsky/login")
    assert res_login.status_code == 200, f"Expected 200 on /indi-allsky/login, got {res_login.status_code}"
    login_html = res_login.get_data(as_text=True)

    for asset, min_bytes in [
        ("/indi-allsky/static/css/dist.css", 1000),
        ("/indi-allsky/sw.js", 100),
        ("/indi-allsky/manifest.json", 50),
        ("/indi-allsky/static/js/jquery-3.7.1.min.js", 1000),
    ]:
        res_asset = client.get(asset)
        assert res_asset.status_code == 200, f"Expected 200 on {asset}, got {res_asset.status_code}"
        assert len(res_asset.data) > min_bytes, f"Asset {asset} is empty or truncated ({len(res_asset.data)} bytes)"

    # 3. Extract CSRF token from login form
    csrf_match = re.search(r"name=['\"]csrf_token['\"][^>]*value=['\"]([^'\"]+)['\"]", login_html) or \
                 re.search(r"value=['\"]([^'\"]+)['\"][^>]*name=['\"]csrf_token['\"]", login_html)
    assert csrf_match is not None, "CSRF token missing from login page HTML"
    csrf_token = csrf_match.group(1)

    # 4. Authenticate as preseeded admin user
    login_res = client.post(
        "/indi-allsky/login",
        json={
            "USERNAME": "admin",
            "PASSWORD": "testpassword123",
            "NEXT": "",
            "csrf_token": csrf_token,
        },
        headers={"X-CSRFToken": csrf_token},
    )
    assert login_res.status_code == 200, f"Admin login failed with HTTP {login_res.status_code}: {login_res.get_data(as_text=True)}"

    # 5. Authenticated HTML web routes rendering sweep (excluding camera-required pages on fresh install)
    routes = [
        "/indi-allsky/",
        "/indi-allsky/config",
        "/indi-allsky/system",
        "/indi-allsky/users",
        "/indi-allsky/sensor_panel",
        "/indi-allsky/charts",
        "/indi-allsky/imageviewer",
        "/indi-allsky/gallery",
        "/indi-allsky/videoviewer",
        "/indi-allsky/minivideoviewer",
        "/indi-allsky/generate",
        "/indi-allsky/config/list",
        "/indi-allsky/config/restore",
        "/indi-allsky/support",
        "/indi-allsky/user",
        "/indi-allsky/cameras",
        "/indi-allsky/tasks",
        "/indi-allsky/notifications",
        "/indi-allsky/darks",
        "/indi-allsky/mask",
        "/indi-allsky/filespaceusage",
        "/indi-allsky/virtualsky",
        "/indi-allsky/sqm",
        "/indi-allsky/astropanel",
    ]
    for route in routes:
        resp = client.get(route)
        assert resp.status_code == 200, f"Route {route} failed with HTTP {resp.status_code}: {resp.get_data(as_text=True)[:300]}"

    # 6. Read-only JSON and AJAX endpoint sweep
    for json_route in ["/indi-allsky/ajax/system/stats"]:
        jresp = client.get(json_route)
        assert jresp.status_code == 200 and jresp.get_json() is not None, f"JSON route {json_route} failed with HTTP {jresp.status_code}"

    for cam_json_route in [
        "/indi-allsky/js/support",
        "/indi-allsky/js/latest",
        "/indi-allsky/js/charts",
        "/indi-allsky/js/sensor_panel",
        "/indi-allsky/ajax/status_update",
        "/indi-allsky/ajax/notification",
    ]:
        cresp = client.get(cam_json_route)
        assert cresp.status_code in (200, 400) and cresp.get_json() is not None, f"JSON route {cam_json_route} failed with HTTP {cresp.status_code}"

    # 7. Config save round-trip, CSRF enforcement, negative validation, and config download
    cfg_resp = client.get("/indi-allsky/config")
    assert cfg_resp.status_code == 200
    cfg_html = cfg_resp.get_data(as_text=True)

    fn_match = re.search(r"const\s+field_names\s*=\s*\[(.*?)\];", cfg_html, re.S)
    cb_match = re.search(r"const\s+checkbox_field_names\s*=\s*\[(.*?)\];", cfg_html, re.S)
    assert fn_match is not None and cb_match is not None, "field_names or checkbox_field_names missing from /indi-allsky/config"

    field_names = re.findall(r"['\"]([^'\"]+)['\"]", fn_match.group(1))
    checkbox_field_names = re.findall(r"['\"]([^'\"]+)['\"]", cb_match.group(1))

    parser = ConfigFormParser()
    parser.feed(cfg_html)

    payload = {}
    missing_dom = []
    for fn in field_names:
        if fn in parser.selects:
            payload[fn] = parser.selects[fn]
        elif fn in parser.textareas:
            payload[fn] = parser.textareas[fn]
        elif fn in parser.inputs:
            payload[fn] = parser.inputs[fn]
        elif fn != "csrf_token":
            missing_dom.append(fn)

    for cb in checkbox_field_names:
        if cb in parser.checkboxes:
            payload[cb] = parser.checkboxes[cb]
        else:
            missing_dom.append(cb)

    assert not missing_dom, f"Config fields missing from rendered HTML DOM: {missing_dom}"
    cfg_csrf = parser.inputs.get("csrf_token", csrf_token)

    # 7a. Missing CSRF token must be rejected
    nocsrf_res = client.post("/indi-allsky/ajax/config", json=payload)
    assert nocsrf_res.status_code == 400, f"Expected HTTP 400 without X-CSRFToken, got {nocsrf_res.status_code}"

    # 7b. Valid config save round-trip
    with application.app_context():
        before_count = IndiAllSkyDbConfigTable.query.count()

    save_res = client.post("/indi-allsky/ajax/config", json=payload, headers={"X-CSRFToken": cfg_csrf})
    assert save_res.status_code == 200, f"Config save failed with HTTP {save_res.status_code}: {save_res.get_data(as_text=True)}"
    save_json = save_res.get_json() or {}
    assert "success-message" in save_json, f"Config save response missing success-message: {save_json}"

    with application.app_context():
        after_count = IndiAllSkyDbConfigTable.query.count()
        latest_cfg = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        assert after_count > before_count and latest_cfg is not None, "Config save did not persist a new database row"
        latest_cfg_id = latest_cfg.id

    # 7c. Negative validation check
    bad_payload = dict(payload)
    bad_payload["LOCATION_LATITUDE"] = "not-a-number"
    bad_res = client.post("/indi-allsky/ajax/config", json=bad_payload, headers={"X-CSRFToken": cfg_csrf})
    assert bad_res.status_code == 400, f"Expected HTTP 400 for invalid LOCATION_LATITUDE, got {bad_res.status_code}"
    bad_json = bad_res.get_json()
    assert isinstance(bad_json, dict) and "LOCATION_LATITUDE" in bad_json, f"Expected LOCATION_LATITUDE validation error, got {bad_json}"

    # 7d. Config download export check
    dl_res = client.get(f"/indi-allsky/config/download?id={latest_cfg_id}")
    assert dl_res.status_code == 200 and isinstance(dl_res.get_json(), dict), f"Config download failed: HTTP {dl_res.status_code}"

    # 8. Logout terminates session
    logout_res = client.get("/indi-allsky/logout")
    assert logout_res.status_code in (200, 302), f"Logout returned unexpected HTTP {logout_res.status_code}"
    post_logout_res = client.get("/indi-allsky/config")
    assert post_logout_res.status_code in (302, 401, 403), f"Expected auth block after logout, got {post_logout_res.status_code}"

print("All authenticated web routes, JSON endpoints, config save round-trip, CSRF/auth, and logout probes passed!")
PYEOF

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

# Verify Alembic migration state matches SQLAlchemy models
FLASK_APP="indi_allsky.flask:create_app()" PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -m flask db current -d /var/lib/indi-allsky/migrations > /dev/null
FLASK_APP="indi_allsky.flask:create_app()" PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -m flask db check -d /var/lib/indi-allsky/migrations
echo "Alembic database schema check passed!"

echo "============================================================"
echo "=== 6. Testing Non-Interactive Package Upgrade / Reinstall ==="
echo "============================================================"
# Verify that upgrading/reinstalling packages with -y automatically reuses configuration without prompting
apt-get install --reinstall -y "${DEB_FILES[@]}"
test -f /etc/indi-allsky/flask.json
FLASK_APP="indi_allsky.flask:create_app()" PYTHONPATH=/usr/share/indi-allsky /var/lib/indi-allsky/venv/bin/python3 -m flask db check -d /var/lib/indi-allsky/migrations
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
