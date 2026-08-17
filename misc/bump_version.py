#!/usr/bin/env python3
"""
Single-Source-of-Truth Version Bumper for indi-allsky.

Usage:
  python3 misc/bump_version.py 2026.08.2
  python3 misc/bump_version.py --show
"""

import sys
import re
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT_DIR / "indi_allsky" / "version.py"
DEBIAN_CHANGELOG = ROOT_DIR / "debian" / "changelog"
PACKAGE_JSON = ROOT_DIR / "package.json"
BASE_HTML = ROOT_DIR / "indi_allsky" / "flask" / "templates" / "base.html"


def get_current_version():
    content = VERSION_FILE.read_text()
    match = re.search(r'__version__\s*=\s*"indi_v([^"]+)"', content)
    if match:
        return match.group(1)
    return "unknown"


def set_version(new_version, suite="stable"):
    clean_ver = new_version.lstrip("v").replace("indi_v", "")
    print(f"Bumping version to: {clean_ver} (Suite: {suite})")

    # 1. Update indi_allsky/version.py
    v_content = VERSION_FILE.read_text()
    v_content = re.sub(
        r'__version__\s*=\s*"[^"]+"',
        f'__version__ = "indi_v{clean_ver}"',
        v_content
    )
    VERSION_FILE.write_text(v_content)
    print(f" Updated {VERSION_FILE.relative_to(ROOT_DIR)}")

    # 2. Update package.json
    if PACKAGE_JSON.exists():
        data = json.loads(PACKAGE_JSON.read_text())
        data["version"] = clean_ver
        PACKAGE_JSON.write_text(json.dumps(data, indent=2) + "\n")
        print(f" Updated {PACKAGE_JSON.relative_to(ROOT_DIR)}")

    # 3. Update base.html CSS cache-buster default fallback
    if BASE_HTML.exists():
        html_content = BASE_HTML.read_text()
        html_content = re.sub(
            r"(\?v=(?:{{[^}]+}}|'))v\d{4}\.\d{2}\.\d+[^'\"]*",
            rf"\g<1>v{clean_ver}",
            html_content
        )
        BASE_HTML.write_text(html_content)
        print(f" Updated {BASE_HTML.relative_to(ROOT_DIR)}")

    # 4. Dynamically generate/update debian/changelog for package builds
    now_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    changelog_content = DEBIAN_CHANGELOG.read_text() if DEBIAN_CHANGELOG.exists() else ""
    new_entry = f"""indi-allsky ({clean_ver}) {suite}; urgency=medium

  * Automatic build for version {clean_ver} ({suite})

 -- INDI Allsky Maintainers <https://github.com/aaronwmorris/indi-allsky>  {now_str}

"""
    if f"indi-allsky ({clean_ver})" not in changelog_content:
        DEBIAN_CHANGELOG.write_text(new_entry + changelog_content)
        print(f" Generated/Updated {DEBIAN_CHANGELOG.relative_to(ROOT_DIR)} dynamically ({suite})")

    print(f"\nSuccessfully updated version to {clean_ver} ({suite}) across all files!")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == "--show":
        print(f"Current version: {get_current_version()}")
        sys.exit(0)

    new_ver = sys.argv[1]
    suite = sys.argv[2] if len(sys.argv) > 2 else "stable"
    set_version(new_ver, suite=suite)


if __name__ == "__main__":
    main()
