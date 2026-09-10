# indi-allsky Test Suite

This directory contains the automated test suite for `indi-allsky`. The test suite is built on [pytest](https://docs.pytest.org/), [pytest-cov](https://pytest-cov.readthedocs.io/), and [pytest-xdist](https://pytest-xdist.readthedocs.io/), designed to provide fast, isolated, and comprehensive coverage across all subsystems without requiring physical astronomy hardware or cloud accounts.

---

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [Running Tests](#running-tests)
   - [NPM Scripts (Recommended)](#npm-scripts-recommended)
   - [Direct Pytest Commands](#direct-pytest-commands)
   - [Targeting Specific Tests and Modules](#targeting-specific-tests-and-modules)
   - [Coverage Reporting](#coverage-reporting)
3. [Test Directory Structure](#test-directory-structure)
4. [When to Add New Subfolders](#when-to-add-new-subfolders)
5. [Architecture & Testing Guidelines](#architecture--testing-guidelines)
   - [Global Configuration & Shared Fixtures (`conftest.py`)](#global-configuration--shared-fixtures-conftestpy)
   - [Mocking Hardware & External Services](#mocking-hardware--external-services)
   - [Database Isolation](#database-isolation)
   - [Filesystem and Temporary Directories](#filesystem-and-temporary-directories)
6. [Checklist for Writing New Tests](#checklist-for-writing-new-tests)

---

## Environment Setup

### 1. Prerequisites

- **Python**: 3.10 or newer (tested up through Python 3.14).
- **Node.js & npm**: Used for package lifecycle scripts and asset builds.
- **C/C++ Build Dependencies**: Certain optional packages (e.g. `simplejpeg`, `PyWavelets`, `sep`) require compiler headers (`gcc`, `libjpeg-dev`, `python3-dev`) if pre-built wheels are unavailable.

### 2. Automated Setup (Recommended)

When initializing the repository via npm:
```bash
npm install
```
This automatically runs the `postinstall` script, executing `npm run setup:venv`:
- Creates a Python virtual environment at `.venv` using `--system-site-packages` (to access system INDI/camera libraries if present).
- Upgrades `pip`, `setuptools`, and `wheel`.
- Installs all testing and development requirements from [`requirements/requirements_testing.txt`](../requirements/requirements_testing.txt).

You can re-run this setup step at any time:
```bash
npm run setup:venv
```

### 3. Manual Virtual Environment Setup

If you prefer to configure Python manually:
```bash
python3 -m venv .venv --system-site-packages
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -r requirements/requirements_testing.txt
```

---

## Running Tests

### NPM Scripts (Recommended)

The project defines convenient shortcuts in [`package.json`](../package.json):

| Command | Description |
| :--- | :--- |
| `npm run test` (or `npm run tests`) | Runs the complete test suite in parallel (`-n auto`) with test coverage reporting across `indi_allsky/`. |
| `npm run test:core` | Runs all tests in `tests/core/` (backend daemons, calculation engines, file transfers). |
| `npm run test:devices` | Runs all tests in `tests/devices/` (camera drivers, hardware sensors, GPS, relays). |
| `npm run test:flask` | Runs all tests in `tests/flask/` (Flask UI routes, API endpoints, auth/OIDC, database models). |
| `npm run test:image` | Runs all tests in `tests/image/` (image processing, computer vision, timelapses, keograms). |
| `npm run test:lens_solver` | Runs all tests in `tests/lens_solver/` (astrometric calibration and lens distortion models). |

### Direct Pytest Commands

You can run `pytest` directly using the virtual environment interpreter:

```bash
# Run the entire test suite
.venv/bin/python -m pytest

# Run with parallel execution across all CPU cores
.venv/bin/python -m pytest -n auto

# Run quietly or disable sugar formatting (helpful for CI logs)
.venv/bin/python -m pytest -p no:sugar -v
```

### Targeting Specific Tests and Modules

To target a single test file:
```bash
.venv/bin/python -m pytest tests/core/test_misc_upload.py
```

To run a specific test class or function:
```bash
.venv/bin/python -m pytest tests/core/test_misc_upload.py -k "test_upload_video_variants"
```

To stop execution on the first failure (`-x`):
```bash
.venv/bin/python -m pytest -x
```

### Coverage Reporting

Coverage configuration is defined in [`pytest.ini`](../pytest.ini). To measure coverage for a specific module or package:

```bash
# Measure coverage for a single file with line numbers of missing statements
.venv/bin/python -m pytest tests/core/test_misc_upload.py --cov=indi_allsky.miscUpload --cov-report=term-missing

# Measure coverage for the entire image processing subsystem
.venv/bin/python -m pytest tests/image/ --cov=indi_allsky.processing --cov-report=term-missing

# Generate an interactive HTML coverage report
.venv/bin/python -m pytest tests/ --cov=indi_allsky --cov-report=html
# Open htmlcov/index.html in your browser
```

---

## Test Directory Structure

The test suite mirrors the modular architecture of `indi_allsky/`:

```
tests/
├── conftest.py               # Global fixtures, mock environments, test database lifecycle
├── core/                     # Core backend services and calculations
│   ├── test_allsky_main.py   # Daemon execution lifecycle and signals
│   ├── test_astro_calcs.py   # Astronomical ephemeris, sun/moon positions
│   ├── test_capture.py       # Main exposure orchestration loop
│   ├── test_filetransfer*.py # Upload engines (boto3, pycurl, paramiko, GCP, Libcloud, OCI)
│   └── test_misc_upload.py   # Secondary upload queuing, sync API, YouTube dispatch
├── devices/                  # Hardware abstractions and sensor drivers
│   ├── test_camera_*.py      # INDI cameras, libcamera MQTT, pycurl camera, simulator
│   ├── test_sensors_*.py     # AS3935 lightning, Si1145, TSL2591, MQTT broker sensors
│   ├── test_focuser.py       # Focuser interfaces
│   └── test_gps.py           # GPS serial / NMEA parsers
├── flask/                    # Flask web application, models, and authentication
│   ├── test_app_factory.py   # Application factory and configuration loader
│   ├── test_auth_views.py    # Local login, registration, and OIDC auth callbacks
│   ├── test_image_endpoints.py # REST endpoints for images and latest feeds
│   └── test_models.py        # SQLAlchemy models and database integrity
├── image/                    # Computer vision, overlays, and video rendering
│   ├── test_image_processor.py # Image calibration, stretches, debayering
│   ├── test_image_worker.py  # Image processing worker process
│   ├── test_stars.py         # Star detection and catalog matching
│   ├── test_timelapse.py     # Video encoding and timelapse builders
│   └── test_asi676mc_*.py    # Sensor defect compensation algorithms
└── lens_solver/              # Astrometry and lens optical geometry
    ├── test_lens_solver_catalog.py
    ├── test_lens_solver_detect.py
    ├── test_lens_solver_fit.py
    └── test_lens_solver_projection.py
```

---

## When to Add New Subfolders

Add a new subfolder under `tests/` when:

1. **A New Architectural Subsystem Is Introduced**: When a new top-level package or independent subsystem is created inside `indi_allsky/` (for example, if machine learning classification or weather station drivers are moved into a dedicated subpackage).
2. **Distinct Fixture Requirements**: When a family of tests shares domain-specific fixtures, test assets (sample images, calibration tables), or execution characteristics that should be grouped cleanly.
3. **Subsystem Size & Cohesion**: When an existing test folder becomes overcrowded with multiple unrelated domains.

### Steps When Adding a New Subfolder

1. Create the subfolder under `tests/` (e.g. `tests/analytics/`).
2. Add an `__init__.py` file if packaging requires it.
3. Add domain-specific fixtures in a local `conftest.py` if needed.
4. Add a corresponding npm test script to [`package.json`](../package.json):
   ```json
   "test:analytics": ".venv/bin/python -m pytest tests/analytics/"
   ```
5. Update this `README.md` to document the new folder's scope.

---

## Architecture & Testing Guidelines

### Global Configuration & Shared Fixtures (`conftest.py`)

The root [`tests/conftest.py`](conftest.py) manages test setup automatically:

- **Headless & Native Mocking**: Mocks native libraries (`PyIndi`, `serial`, `gunicorn`) when running on developer machines or CI runners without INDI drivers.
- **Isolated Flask Config**: Generates a temporary JSON configuration from `flask.json_template` with testing flags, random secrets, and a temporary SQLite database.
- **`flask_app` / `app`**: Session-scoped fixture providing an initialized Flask application context.
- **`db`**: Provides a clean SQLAlchemy session per test.
- **`clean_database_tables`**: An `autouse=True` fixture that rolls back sessions and clears all database table rows between tests, preventing state pollution.
- **`base_config`**: Returns a standardized dictionary representing the full INDI AllSky configuration, redirected to temporary directories (`tmp_path`).

### Mocking Hardware & External Services

Tests should **never** make real network calls, connect to real cloud buckets (AWS/GCP/OCI), or attempt real serial/I2C I/O.

- Use `unittest.mock.MagicMock` or `unittest.mock.patch` to mock external API clients.
- When testing cloud drivers (`boto3`, `google.cloud`, `libcloud`, `oci`), mock modules via `sys.modules` or `patch.dict(sys.modules, ...)` so tests pass even when cloud SDKs are not installed locally.
- For sensors, mock the underlying hardware communication bus (I2C, SPI, SMBus, PySerial) and verify that sensor read/write methods translate raw values to physical units correctly.

### Database Isolation

- Always wrap database operations inside `with app.app_context():`.
- The `clean_database_tables` fixture guarantees an empty database before each test. If your test creates database rows (such as cameras, images, or task queues), commit them normally; they will be wiped automatically at test teardown.

### Filesystem and Temporary Directories

- Never hardcode `/tmp` paths or write directly into the repository working tree.
- Use pytest's built-in [`tmp_path`](https://docs.pytest.org/en/stable/how-to/tmp_path.html) fixture (a `pathlib.Path` pointing to an isolated, temporary directory per test):
  ```python
  def test_file_output(tmp_path):
      test_file = tmp_path / "sample.jpg"
      test_file.write_bytes(b"image data")
      assert test_file.exists()
  ```

---

## Checklist for Writing New Tests

When contributing new features or refactoring existing code, ensure:

- [ ] **Deterministic Execution**: Tests must pass regardless of execution order (`pytest-randomly` compatible).
- [ ] **Parallel Safe**: Tests must run without race conditions when executed with `-n auto`.
- [ ] **High Coverage**: Aim for 90%+ code coverage for new modules, verifying both success paths and error branches (`term-missing`).
- [ ] **Fast Runtime**: Unit tests should execute in milliseconds; mock long sleeps, large image iterations, and slow network retries.
- [ ] **Cleanup**: Any mocked global state (`sys.modules`, environment variables) must be restored after the test completes.
- [ ] **Passing Suite**: Run `npm run test` before committing to verify zero regressions across the entire suite.
