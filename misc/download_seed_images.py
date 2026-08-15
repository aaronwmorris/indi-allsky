#!/usr/bin/env python3
"""
Seed Images Downloader for indi-allsky.

This script connects to a live `indi-allsky` instance (via interactive prompt or `--url`)
to download authentic sample media assets and saves them into `content/screenshots/seedImages/`
matching the seed image naming schema:
  - latest.jpg
  - gallery_01.jpg .. gallery_16.jpg
  - keogram_night_01.jpg .. keogram_night_05.jpg
  - keogram_day_01.jpg .. keogram_day_05.jpg
  - startrails_01.jpg .. startrails_05.jpg
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

# Ensure repo root is in python path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SEED_DIR = REPO_ROOT / "content" / "screenshots" / "seedImages"


def ensure_playwright():
    """Ensure Playwright module and Chromium browser are installed."""
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


def download_seed_images(instance_url, seed_dir):
    """Downloads sample media from a live indi-allsky instance and formats them according to the seed schema."""
    from playwright.sync_api import sync_playwright

    url = instance_url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if url.endswith("/indi-allsky"):
        base_app_url = url
    else:
        base_app_url = f"{url}/indi-allsky"

    seed_dir = Path(seed_dir).resolve()
    seed_dir.mkdir(parents=True, exist_ok=True)

    print(f"[+] Connecting to live instance: {base_app_url}")
    print(f"[+] Output seed directory: {seed_dir}")

    success_count = 0
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    def download_file(source_url, target_file):
        nonlocal success_count
        try:
            full_target_url = urllib.parse.urljoin(f"{base_app_url}/", source_url)
            req = urllib.request.Request(full_target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                target_file.write_bytes(data)
                success_count += 1
                return True
        except Exception as e:
            print(f"  [!] Failed downloading {source_url}: {e}")
            return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Latest Home Page Capture Image -> latest.jpg
        print("\n -> Fetching latest camera capture image...")
        try:
            page.goto(f"{base_app_url}/")
            page.wait_for_selector(".tw\\:card, #latest_image, canvas, img", timeout=8000)
            page.wait_for_timeout(2000)
            main_imgs = [
                img.get_attribute("src")
                for img in page.locator("img").all()
                if img.get_attribute("src")
            ]
            for src in main_imgs:
                if "logo" not in src.lower() and "static" not in src.lower():
                    if download_file(src, seed_dir / "latest.jpg"):
                        print("  [✔] Saved latest.jpg")
                        break
        except Exception as e:
            print(f"  [!] Could not fetch main home page image: {e}")

        # 2. Gallery Thumbnails & Images -> gallery_01.jpg .. gallery_16.jpg
        print("\n -> Fetching gallery thumbnails...")
        try:
            page.goto(f"{base_app_url}/gallery")
            page.wait_for_selector("#allsky-gallery img, .tw\\:grid img, img", timeout=8000)
            page.wait_for_timeout(2000)

            downloaded_urls = set()
            g_idx = 0

            def collect_gallery_imgs():
                nonlocal g_idx
                imgs = page.locator("#allsky-gallery img, img").all()
                for img_loc in imgs:
                    src = img_loc.get_attribute("src")
                    if not src or "logo" in src.lower() or "static" in src.lower():
                        continue
                    if src in downloaded_urls:
                        continue
                    downloaded_urls.add(src)
                    target_fn = f"gallery_{g_idx + 1:02d}.jpg"
                    if download_file(src, seed_dir / target_fn):
                        g_idx += 1
                        if g_idx >= 16:
                            break

            collect_gallery_imgs()

            if g_idx < 16:
                hour_select = page.locator("#HOUR_SELECT")
                if hour_select.count() > 0:
                    options = hour_select.locator("option").all()
                    for opt in options:
                        val = opt.get_attribute("value")
                        if not val:
                            continue
                        hour_select.select_option(val)
                        page.wait_for_timeout(1500)
                        collect_gallery_imgs()
                        if g_idx >= 16:
                            break

            print(f"  [✔] Downloaded {g_idx} gallery seed images")
        except Exception as e:
            print(f"  [!] Could not fetch gallery images: {e}")

        # 3. Keograms and Star Trails -> keogram_night_XX.jpg / keogram_day_XX.jpg / startrails_XX.jpg
        print("\n -> Fetching keograms and star trails from timelapse viewer...")
        try:
            page.goto(f"{base_app_url}/videoviewer")
            page.wait_for_selector(".tw\\:card, img, a", timeout=8000)
            page.wait_for_timeout(2000)

            keogram_urls = []
            startrail_urls = []

            for a in page.locator("a").all():
                href = a.get_attribute("href") or ""
                img = a.locator("img")
                if img.count() > 0:
                    src = img.first.get_attribute("src")
                    if src and "logo" not in src.lower() and "static" not in src.lower():
                        if "/view_keogram" in href:
                            if src not in keogram_urls:
                                keogram_urls.append(src)
                        elif "/view_startrail" in href:
                            if src not in startrail_urls:
                                startrail_urls.append(src)

            k_night_idx = 0
            for k_src in keogram_urls[:5]:
                target_fn = f"keogram_night_{k_night_idx + 1:02d}.jpg"
                if download_file(k_src, seed_dir / target_fn):
                    k_night_idx += 1

            s_idx = 0
            for s_src in startrail_urls[:5]:
                target_fn = f"startrails_{s_idx + 1:02d}.jpg"
                if download_file(s_src, seed_dir / target_fn):
                    s_idx += 1

            print(f"  [✔] Saved {k_night_idx} keogram seeds and {s_idx} star trail seeds")
        except Exception as e:
            print(f"  [!] Could not fetch videoviewer previews: {e}")

        browser.close()

    if success_count == 0:
        raise RuntimeError(f"Failed to fetch any images from {instance_url}. Please check the instance URL.")

    # Fill in missing schema slots with category-isolated fallback copies if needed
    existing_gallery = sorted(list(seed_dir.glob("gallery_*.jpg")))
    existing_k_night = sorted(list(seed_dir.glob("keogram_night_*.jpg")))
    existing_k_day = sorted(list(seed_dir.glob("keogram_day_*.jpg")))
    existing_keograms = existing_k_night or existing_k_day or sorted([f for f in seed_dir.glob("keogram_*.jpg")])
    existing_startrails = sorted(list(seed_dir.glob("startrails_*.jpg")))
    all_downloaded = sorted(list(seed_dir.glob("*.jpg")))

    gallery_pool = existing_gallery if existing_gallery else all_downloaded
    k_night_pool = existing_k_night if existing_k_night else (existing_keograms if existing_keograms else all_downloaded)
    k_day_pool = existing_k_day if existing_k_day else (existing_keograms if existing_keograms else all_downloaded)
    s_pool = existing_startrails if existing_startrails else all_downloaded

    if not (seed_dir / "latest.jpg").exists():
        shutil.copy(all_downloaded[0], seed_dir / "latest.jpg")

    for idx in range(16):
        fn = seed_dir / f"gallery_{idx + 1:02d}.jpg"
        if not fn.exists():
            shutil.copy(gallery_pool[idx % len(gallery_pool)], fn)

    for idx in range(5):
        fn_k_night = seed_dir / f"keogram_night_{idx + 1:02d}.jpg"
        fn_k_day = seed_dir / f"keogram_day_{idx + 1:02d}.jpg"
        fn_s = seed_dir / f"startrails_{idx + 1:02d}.jpg"
        if not fn_k_night.exists():
            shutil.copy(k_night_pool[idx % len(k_night_pool)], fn_k_night)
        if not fn_k_day.exists():
            shutil.copy(k_day_pool[idx % len(k_day_pool)], fn_k_day)
        if not fn_s.exists():
            shutil.copy(s_pool[idx % len(s_pool)], fn_s)

    print(f"\n[✔] Seed images successfully populated in: {seed_dir} ({success_count} assets downloaded)")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Download authentic seed images from a live indi-allsky instance."
    )
    parser.add_argument(
        "--url",
        type=str,
        default="",
        help="Live indi-allsky instance URL (e.g. https://allsky.example.com)",
    )
    parser.add_argument(
        "--output-dir",
        "--out",
        type=str,
        default=str(DEFAULT_SEED_DIR),
        help=f"Target directory to save seed images (default: {DEFAULT_SEED_DIR})",
    )
    args = parser.parse_known_args()[0]

    instance_url = args.url.strip()
    if not instance_url and sys.stdin.isatty():
        try:
            print("\n" + "=" * 70)
            user_input = input(
                "[?] Enter an indi-allsky live instance URL (e.g. https://allsky.example.com): "
            ).strip()
            print("=" * 70 + "\n")
            if user_input:
                instance_url = user_input
        except (EOFError, KeyboardInterrupt):
            pass

    if not instance_url:
        print("[!] Error: An indi-allsky instance URL is required. Specify --url (e.g. python3 misc/download_seed_images.py --url https://allsky.example.com)")
        sys.exit(1)

    ensure_playwright()
    download_seed_images(instance_url, args.output_dir)


if __name__ == "__main__":
    main()
