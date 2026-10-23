"""Run the bilateral visibility JavaScript regressions through pytest."""

import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path


class BilateralRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            self.rows.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == "div":
            self.rows.pop()

    def handle_data(self, data):
        for field in (
            "BILATERAL_SIGMA_COLOR", "BILATERAL_SIGMA_SPACE",
            "BILATERAL_SIGMA_COLOR_DAY", "BILATERAL_SIGMA_SPACE_DAY",
        ):
            if f".{field}(" in data:
                self.fields[field] = [
                    row for row in self.rows
                    if row.get("id", "").startswith("bilateral-settings")
                ]


def test_bilateral_rows_include_fields_and_start_hidden():
    templates = Path(__file__).resolve().parents[2] / "indi_allsky" / "flask" / "templates"
    for template in ("config/image.html", "imageprocessing.html"):
        parser = BilateralRows()
        parser.feed((templates / template).read_text(encoding="utf-8"))
        suffixes = ("", "_DAY") if template == "config/image.html" else ("",)
        for suffix in suffixes:
            for field in ("BILATERAL_SIGMA_COLOR", "BILATERAL_SIGMA_SPACE"):
                rows = parser.fields[field + suffix]
                assert len(rows) == 1
                assert rows[0]["id"] == ("bilateral-settings-day" if suffix else "bilateral-settings")
                assert rows[0]["style"] == "display: none;"


def test_bilateral_visibility():
    node = shutil.which("node")
    assert node is not None, "Node.js is required to run the bilateral visibility tests"

    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("bilateral_visibility.test.cjs"))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
