#!/usr/bin/env python3
"""
Automated README Screenshot Generator for indi-allsky.

This script connects to a live `indi-allsky` instance (via interactive prompt or `--url`)
to download authentic sample media assets (latest capture image, gallery thumbnails,
keogram previews, and star trail previews). It populates a local Flask test database and
uses Playwright headless Chromium to capture high-resolution (1920x1080) README screenshots into `content/`.
"""

import os
import sys
import time
import datetime
import threading
import tempfile
import subprocess
import math
from pathlib import Path

# Ensure repo root is in python path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Output directory for screenshots & seed images
CONTENT_DIR = REPO_ROOT / "content" / "screenshots"
SEED_DIR = CONTENT_DIR / "seedImages"
CONTENT_DIR.mkdir(parents=True, exist_ok=True)
SEED_DIR.mkdir(parents=True, exist_ok=True)


# 1. Playwright Setup Check
def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
    except Exception as e:
        print(f"[!] Playwright browser/package not ready ({e}). Auto-installing...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        except Exception as pip_err:
            print(f"[!] Warning: pip install playwright failed: {pip_err}")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"], check=True
        )


ensure_playwright()

# Mock heavy optional dependencies if not present
from unittest.mock import MagicMock
from importlib.machinery import ModuleSpec


class MagicMockModuleLoader:
    def create_module(self, spec):
        return MagicMock()

    def exec_module(self, module):
        pass


class MissingModuleMockFinder:
    MISSING_PREFIXES = (
        "astroalign",
        "ccdproc",
        "astropy",
        "scipy",
        "piexif",
        "boto3",
        "paramiko",
        "paho",
        "is_safe_url",
        "gunicorn",
    )

    def find_spec(self, fullname, path, target=None):
        if any(
            fullname == m or fullname.startswith(m + ".") for m in self.MISSING_PREFIXES
        ):
            spec = ModuleSpec(fullname, MagicMockModuleLoader())
            spec.submodule_search_locations = []
            return spec
        return None


sys.meta_path.insert(0, MissingModuleMockFinder())

import uuid
from playwright.sync_api import sync_playwright
import passlib.hash

passlib.hash.argon2.hash = lambda pwd: f"hashed_{pwd}"
passlib.hash.argon2.verify = lambda pwd, hash_val: hash_val == f"hashed_{pwd}"
from passlib.hash import argon2
from indi_allsky.flask import create_app, db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbStateTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbThumbnailTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbUserTable,
)


def build_chart_01_data():
    """Early evening sunset + cloud bump scenario."""
    jsqm = []
    stars = []
    temp = []
    exp = []
    gain = []

    # 19:06:11 to 19:48:57 (85 points)
    base_time = datetime.datetime(2026, 8, 14, 19, 6, 11)
    total_points = 85
    for i in range(total_points):
        t_sec = i * 30  # 0 to 2520 seconds
        t = base_time + datetime.timedelta(seconds=t_sec)
        t_str = t.strftime("%H:%M:%S")

        # 1. Sunset twilight drop (0 to 500s / i 0..16)
        if i <= 16:
            val_sqm = 16800 * math.exp(-0.02 * i) + math.sin(i * 0.5) * 120
            val_stars = 135 + i * 1.3 + math.sin(i * 0.7) * 7
        # 2. Cloud pass bump (i 17..26, centered around i=21 / 19:16:41)
        elif 16 < i <= 26:
            dist = (i - 21) / 3.0
            gaussian = math.exp(-(dist**2))
            val_sqm = 12000 + 3200 * gaussian + math.sin(i) * 90
            val_stars = 158 - 56 * gaussian + math.cos(i) * 5
        # 3. Post-cloud night leveling off (i 27..84 / 19:19 to 19:48)
        else:
            decay = math.exp(-(i - 26) / 20.0)
            val_sqm = 9800 + 1500 * decay + math.sin(i * 0.3) * 120
            val_stars = 160 + math.sin(i * 0.4) * 14 + math.cos(i * 0.9) * 6

        jsqm.append({"x": t_str, "y": round(val_sqm, 1)})
        stars.append({"x": t_str, "y": max(0, int(val_stars))})
        temp.append({"x": t_str, "y": 18.2})
        exp.append({"x": t_str, "y": 15.0})
        gain.append({"x": t_str, "y": 250})

    jsqm_d = []
    for idx in range(len(jsqm)):
        diff = jsqm[idx]["y"] - jsqm[idx - 1]["y"] if idx > 0 else 0
        jsqm_d.append({"x": jsqm[idx]["x"], "y": round(diff, 1)})

    return {
        "chart_data": {
            "jsqm": jsqm,
            "jsqm_d": jsqm_d,
            "stars": stars,
            "temp": temp,
            "exp": exp,
            "gain": gain,
            "detection": [],
            "custom_1": [],
            "custom_2": [],
            "custom_3": [],
            "custom_4": [],
            "custom_5": [],
            "custom_6": [],
            "custom_7": [],
            "custom_8": [],
            "custom_9": [],
            "histogram": {"red": [], "green": [], "blue": [], "gray": []},
        },
        "message": "",
    }


def build_chart_02_data():
    """Large cloud overcast scenario (huge SQM spike & stars drop to zero)."""
    jsqm = []
    stars = []
    temp = []
    exp = []
    gain = []

    # 20:35:44 to 21:34:32 (100 points)
    base_time = datetime.datetime(2026, 8, 14, 20, 35, 44)
    total_points = 100
    for i in range(total_points):
        t_sec = i * 35  # 0 to 3465 seconds
        t = base_time + datetime.timedelta(seconds=t_sec)
        t_str = t.strftime("%H:%M:%S")

        # Clear night sky (i 0..82 / 20:35 to 21:26)
        if i <= 82:
            val_sqm = 9200 + math.sin(i * 0.25) * 550 + math.cos(i * 0.6) * 250
            val_stars = 162 + math.sin(i * 0.35) * 18 + math.cos(i * 0.8) * 8
        # Overcast cloud surge (i 83..99 / 21:27 to 21:34)
        else:
            progress = (i - 82) / 17.0
            val_sqm = 9200 + (progress**2.5) * 29000
            val_stars = 162 * (1.0 - progress**0.7) + math.sin(i) * 3

        jsqm.append({"x": t_str, "y": round(val_sqm, 1)})
        stars.append({"x": t_str, "y": max(4, int(val_stars))})
        temp.append({"x": t_str, "y": 17.1})
        exp.append({"x": t_str, "y": 15.0})
        gain.append({"x": t_str, "y": 250})

    jsqm_d = []
    for idx in range(len(jsqm)):
        diff = jsqm[idx]["y"] - jsqm[idx - 1]["y"] if idx > 0 else 0
        jsqm_d.append({"x": jsqm[idx]["x"], "y": round(diff, 1)})

    return {
        "chart_data": {
            "jsqm": jsqm,
            "jsqm_d": jsqm_d,
            "stars": stars,
            "temp": temp,
            "exp": exp,
            "gain": gain,
            "detection": [],
            "custom_1": [],
            "custom_2": [],
            "custom_3": [],
            "custom_4": [],
            "custom_5": [],
            "custom_6": [],
            "custom_7": [],
            "custom_8": [],
            "custom_9": [],
            "histogram": {"red": [], "green": [], "blue": [], "gray": []},
        },
        "message": "",
    }





def seed_database(db, img_dir):
    """Populates test database with initial records."""
    try:
        now_tz = datetime.datetime.now().astimezone()
        offset_hours = now_tz.utcoffset().total_seconds() / 3600.0
        calculated_lon = round(offset_hours * 15.0, 4)
        calculated_lat = 33.7490

        # Camera
        cam = IndiAllSkyDbCameraTable(
            id=1,
            name="ZWO ASI678MC",
            latitude=calculated_lat,
            longitude=calculated_lon,
            elevation=300,
            nightSunAlt=-6.0,
            maxExposure=300.0,
            maxGain=500.0,
            local=True,
        )
        db.session.add(cam)

        # Admin User
        admin_user = IndiAllSkyDbUserTable(
            id=1,
            username="admin",
            email="admin@example.com",
            active=True,
            admin=True,
            password=argon2.hash("admin123"),
        )
        db.session.add(admin_user)

        # Config table defaults
        cfg = IndiAllSkyDbConfigTable(
            id=1,
            level="system",
            note="Initial config",
            data={
                "LOCATION_LATITUDE": calculated_lat,
                "LOCATION_LONGITUDE": calculated_lon,
            },
        )
        db.session.add(cfg)

        state_rec = IndiAllSkyDbStateTable(key="CONFIG_ID", value="1")
        state_wd = IndiAllSkyDbStateTable(key="WATCHDOG", value="9999999999")
        state_st = IndiAllSkyDbStateTable(key="STATUS", value="702")
        db.session.add_all([state_rec, state_wd, state_st])

        # Seed sample images + thumbnails for Gallery & Latest views
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        today_date = datetime.date.today()

        thumb_files = sorted(list(img_dir.glob("thumb_*.jpg")))
        num_items = max(16, len(thumb_files))

        for idx in range(num_items):
            t_uuid = str(uuid.uuid4())
            thumb_fn = f"thumb_{idx:02d}.jpg"
            full_fn = f"full_{idx:02d}.jpg" if idx > 0 else "latest_sample.jpg"

            thumb_rec = IndiAllSkyDbThumbnailTable(
                camera_id=1,
                uuid=t_uuid,
                filename=thumb_fn,
                data={},
            )
            db.session.add(thumb_rec)

            img_dt = now_dt - datetime.timedelta(minutes=idx * 2)
            img_rec = IndiAllSkyDbImageTable(
                camera_id=1,
                thumbnail_uuid=t_uuid,
                filename=full_fn,
                createDate=img_dt,
                createDate_year=now_dt.year,
                createDate_month=now_dt.month,
                createDate_day=now_dt.day,
                createDate_hour=now_dt.hour,
                dayDate=today_date,
                exposure=15.0,
                gain=250,
                temp=17.5,
                adu=125.0,
                sqm=9800 + idx * 50,
                stars=165 - idx * 2,
                data={},
            )
            db.session.add(img_rec)

        # Seed sample videos / keograms / startrails for multiple days & nights
        entries = [
            (today_date, True, "Night", 165, 2.67),
            (today_date, False, "Day", 0, 0.0),
            (today_date - datetime.timedelta(days=1), True, "Night", 172, 1.8),
            (today_date - datetime.timedelta(days=1), False, "Day", 0, 0.0),
            (today_date - datetime.timedelta(days=2), True, "Night", 158, 3.2),
        ]

        import shutil

        keogram_files = sorted(list(img_dir.glob("keogram_[0-9]*.jpg")))
        startrails_files = sorted(list(img_dir.glob("startrails_[0-9]*.jpg")))
        all_jpgs = sorted(list(img_dir.glob("*.jpg")))

        night_idx = 0
        for idx, (d_date, is_night, label, avg_stars, kp) in enumerate(entries):
            tag = "night" if is_night else "day"
            date_str = d_date.strftime("%Y%m%d")
            k_fn = f"keogram_{date_str}_{tag}.jpg"
            s_fn = f"startrails_{date_str}_{tag}.jpg" if is_night else None
            v_fn = f"video_{date_str}_{tag}.mp4"

            # Assign distinct keogram file
            k_source = (
                keogram_files[idx % len(keogram_files)]
                if keogram_files
                else all_jpgs[idx % len(all_jpgs)]
            )
            shutil.copy(k_source, img_dir / k_fn)

            # Assign distinct startrails file for night
            if is_night and s_fn:
                s_source = (
                    startrails_files[night_idx % len(startrails_files)]
                    if startrails_files
                    else all_jpgs[(night_idx + 1) % len(all_jpgs)]
                )
                shutil.copy(s_source, img_dir / s_fn)
                night_idx += 1

            keogram_rec = IndiAllSkyDbKeogramTable(
                camera_id=1,
                filename=k_fn,
                dayDate=d_date,
                night=is_night,
            )
            db.session.add(keogram_rec)

            if is_night and s_fn:
                startrails_rec = IndiAllSkyDbStarTrailsTable(
                    camera_id=1,
                    filename=s_fn,
                    dayDate=d_date,
                    night=is_night,
                )
                db.session.add(startrails_rec)

            video_rec = IndiAllSkyDbVideoTable(
                camera_id=1,
                filename=v_fn,
                dayDate=d_date,
                dayDate_year=d_date.year,
                dayDate_month=d_date.month,
                dayDate_day=d_date.day,
                night=is_night,
                success=True,
                data={
                    "max_stars": avg_stars + 25 if is_night else 0,
                    "avg_stars": avg_stars if is_night else 0,
                    "max_kp": kp if is_night else 0.0,
                    "avg_kp": max(0.0, kp - 0.5) if is_night else 0.0,
                    "max_smoke_rating": 0,
                },
            )
            db.session.add(video_rec)

        db.session.commit()
        print("[+] Database seeded successfully with multiple days and nights.")
    except Exception as e:
        print(f"[!] Exception during database seeding: {e}")
        db.session.rollback()


def load_from_local_dir(source_dir_path, img_dir):
    """Loads sample media images from a specified local directory using schema filenames or generic fallbacks."""
    import shutil

    source_dir = Path(source_dir_path).resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise RuntimeError(
            f"Specified local directory does not exist or is not a directory: {source_dir}"
        )

    valid_extensions = (
        "*.jpg",
        "*.jpeg",
        "*.png",
        "*.webp",
        "*.JPG",
        "*.JPEG",
        "*.PNG",
        "*.WEBP",
    )
    found_images = []
    for ext in valid_extensions:
        found_images.extend(source_dir.glob(ext))

    found_images = sorted(list(set(found_images)))

    if not found_images:
        raise RuntimeError(
            f"No image files (.jpg, .png, .webp) found in directory: {source_dir}"
        )

    print(
        f"[+] Loading {len(found_images)} seed images from local directory: {source_dir}"
    )

    for img_file in found_images:
        shutil.copy(img_file, img_dir / img_file.name)

    # 1. Latest sample capture image schema: latest.* or latest_sample.*
    latest_matches = [
        f for f in found_images if f.stem.lower() in ("latest", "latest_sample")
    ]
    latest_src = latest_matches[0] if latest_matches else found_images[0]
    shutil.copy(latest_src, img_dir / "latest_sample.jpg")

    # 2. Gallery images schema: gallery_XX.* or thumb_XX.* / full_XX.*
    gallery_matches = [
        f
        for f in found_images
        if f.stem.lower().startswith(("gallery_", "thumb_", "full_"))
    ]
    gallery_pool = gallery_matches if gallery_matches else found_images

    for idx in range(16):
        t_file = img_dir / f"thumb_{idx:02d}.jpg"
        f_file = img_dir / f"full_{idx:02d}.jpg"
        src_img = gallery_pool[idx % len(gallery_pool)]
        shutil.copy(src_img, t_file)
        shutil.copy(src_img, f_file)

    # 3. Keograms schema: keogram_night_XX.* / keogram_day_XX.* / keogram_XX.*
    keogram_night_matches = [
        f for f in found_images if "keogram_night" in f.stem.lower()
    ]
    keogram_day_matches = [
        f for f in found_images if "keogram_day" in f.stem.lower()
    ]
    keogram_gen_matches = [f for f in found_images if "keogram" in f.stem.lower()]

    night_k_pool = keogram_night_matches or keogram_gen_matches or found_images
    day_k_pool = (
        keogram_day_matches
        or keogram_night_matches
        or keogram_gen_matches
        or found_images
    )

    for k_i in range(5):
        t_night_path = img_dir / f"keogram_night_{k_i:02d}.jpg"
        t_day_path = img_dir / f"keogram_day_{k_i:02d}.jpg"
        src_night = night_k_pool[k_i % len(night_k_pool)]
        src_day = day_k_pool[k_i % len(day_k_pool)]
        shutil.copy(src_night, t_night_path)
        shutil.copy(src_day, t_day_path)
        shutil.copy(src_night, img_dir / f"keogram_{k_i:02d}.jpg")

    # 4. Star Trails schema: startrails_XX.* / startrail_XX.*
    startrails_matches = [f for f in found_images if "startrail" in f.stem.lower()]
    startrails_pool = startrails_matches or found_images

    for s_i in range(5):
        t_path = img_dir / f"startrails_{s_i:02d}.jpg"
        src_img = startrails_pool[s_i % len(startrails_pool)]
        shutil.copy(src_img, t_path)

    print(
        f"[+] Seed images mapped successfully ({len(found_images)} source files processed)"
    )


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Generate indi-allsky README screenshots."
    )
    parser.add_argument(
        "--image-dir",
        "--dir",
        type=str,
        default="",
        help=f"Path to a local directory containing seed image files (defaults to {SEED_DIR})",
    )
    args = parser.parse_known_args()[0]

    source_dir_path = args.image_dir.strip()

    if not source_dir_path:
        seed_images = []
        if SEED_DIR.exists():
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                seed_images.extend(SEED_DIR.glob(ext))
        if seed_images:
            source_dir_path = str(SEED_DIR)

    if not source_dir_path:
        print(f"[!] Error: No seed images found in {SEED_DIR} and no --image-dir specified.")
        print("    To download seed images from a live instance, run:")
        print("      npm run download-seeds -- --url https://your-allsky-instance.example.com")
        print("      or: python3 misc/download_seed_images.py --url https://your-allsky-instance.example.com")
        sys.exit(1)

    print(f"[+] Using seed images directory: {source_dir_path}")
    print("[+] Setting up Flask test database and sample assets...")

    temp_dir = Path(tempfile.mkdtemp(prefix="allsky_screenshot_test_"))
    db_path = temp_dir / "test_indi_allsky.sqlite"
    img_dir = temp_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    load_from_local_dir(source_dir_path, img_dir)

    # Flask App config
    flask_cfg_file = temp_dir / "flask.json"
    with open(flask_cfg_file, "w") as f:
        f.write(f'''{{
            "SECRET_KEY": "test_secret_key",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///{db_path}",
            "MIGRATION_FOLDER": "{REPO_ROOT / "migrations"}",
            "INDI_ALLSKY_IMAGE_FOLDER": "{img_dir}",
            "INDISERVER_SERVICE_NAME": "indiserver.service",
            "INDISERVER_TIMER_NAME": "indiserver.timer",
            "INDI_ALLSKY_SERVICE_NAME": "indi-allsky.service",
            "INDI_ALLSKY_TIMER_NAME": "indi-allsky.timer",
            "ALLSKY_SERVICE_NAME": "indi-allsky.service",
            "ALLSKY_TIMER_NAME": "indi-allsky.timer",
            "UPGRADE_ALLSKY_SERVICE_NAME": "upgrade-indi-allsky.service",
            "GUNICORN_SERVICE_NAME": "gunicorn-indi-allsky.service",
            "GUNICORN_SOCKET_NAME": "gunicorn-indi-allsky.socket"
        }}''')

    os.environ["INDI_ALLSKY_FLASK_CONFIG"] = str(flask_cfg_file)

    app = create_app()

    with app.app_context():
        db.create_all()
        seed_database(db, img_dir)

    # Launch server in background thread
    PORT = 5099
    server_thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=PORT, debug=False, use_reloader=False
        )
    )
    server_thread.daemon = True
    server_thread.start()
    time.sleep(1.5)  # Wait for Flask to boot

    BASE_URL = f"http://127.0.0.1:{PORT}/indi-allsky"
    print(f"[+] Flask server running on {BASE_URL}")

    chart_01_json = build_chart_01_data()
    chart_02_json = build_chart_02_data()

    print("[+] Launching Playwright to capture screenshots...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
        )
        page = context.new_page()

        # Login
        print(" -> Logging in as admin...")
        page.goto(f"{BASE_URL}/login")
        page.fill("input[name='USERNAME']", "admin")
        page.fill("input[name='PASSWORD']", "admin123")
        page.click("button[type='submit']")
        page.wait_for_selector("aside")
        time.sleep(1)

        # 1. Home Page Screenshot
        print(" -> Capturing Home Page (webui_home.png)...")
        page.goto(f"{BASE_URL}/")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        home_path = str(CONTENT_DIR / "webui_home.png")
        page.screenshot(path=home_path)

        # Helper to inject custom chart payload via route interception for screenshots
        def capture_chart_screenshot(
            output_filename, chart_payload, route_path="/charts"
        ):
            page.route(
                "**/js/charts*",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(chart_payload),
                ),
            )
            page.goto(f"{BASE_URL}/charts")
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            out_path = str(CONTENT_DIR / output_filename)
            page.screenshot(path=out_path)
            page.unroute("**/js/charts*")

        # 2. Chart 01 Screenshot
        print(" -> Capturing Chart 01 (webui_chart01.png)...")
        capture_chart_screenshot("webui_chart01.png", chart_01_json, "/charts")

        # 3. Chart 02 Screenshot
        print(" -> Capturing Chart 02 (webui_chart02.png)...")
        capture_chart_screenshot("webui_chart02.png", chart_02_json, "/charts")

        # 4. Gallery Screenshot
        print(" -> Capturing Gallery (webui_images.png)...")
        page.goto(f"{BASE_URL}/gallery")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        gallery_path = str(CONTENT_DIR / "webui_images.png")
        page.screenshot(path=gallery_path)

        # 5. Timelapse Viewer Screenshot
        print(" -> Capturing Timelapse Viewer (webui_timelapse_mono.png)...")
        page.goto(f"{BASE_URL}/videoviewer")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        timelapse_path = str(CONTENT_DIR / "webui_timelapse_mono.png")
        page.screenshot(path=timelapse_path)

        # 6. System Info Screenshot
        print(" -> Capturing System Info Page (webui_systeminfo.png)...")
        page.goto(f"{BASE_URL}/system")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        system_path = str(CONTENT_DIR / "webui_systeminfo.png")
        page.screenshot(path=system_path)

        # 7. Config Page Screenshot
        print(" -> Capturing Config Page (webui_config.png)...")
        page.goto(f"{BASE_URL}/config#admin")
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        config_path = str(CONTENT_DIR / "webui_config.png")
        page.screenshot(path=config_path)

        browser.close()

    print("[✔] All screenshots generated successfully in content/")


if __name__ == "__main__":
    main()
