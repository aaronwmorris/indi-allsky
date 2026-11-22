# Database Architecture & Design

`indi-allsky` utilizes SQLAlchemy ORM with Flask-SQLAlchemy to manage its data layer. The database acts as both a persistent media metadata store and an inter-process communication (IPC) channel between the background daemon (`allsky.py`) and the Gunicorn WSGI web application.

---

## 1. Supported Storage Engines

* **SQLite (Default)**: Located at `/var/lib/indi-allsky/indi-allsky.sqlite`. Operates with Write-Ahead Logging (`WAL` mode) enabled to support concurrent read operations by the web server while the capture daemon writes frame records.
* **MySQL / MariaDB**: Supported for multi-camera deployments, network-mounted clusters, or remote portal instances where high concurrent write throughput is required.

---

## 2. Table & Model Architecture

Defined in [`indi_allsky/flask/models.py`](https://github.com/aaronwmorris/indi-allsky/blob/main/indi_allsky/flask/models.py):

| Model Class | Database Table | Purpose |
|---|---|---|
| `IndiAllSkyDbCameraTable` | `camera` | Hardware identifiers, coordinates, sensor dimensions, and lens configuration. |
| `IndiAllSkyDbImageTable` | `image` | Metadata for captured frames (exposure, gain, timestamps, star count, detected lines, SQM values, sensor telemetry). |
| `IndiAllSkyDbThumbnailTable` | `thumbnail` | Binary thumbnail previews cached directly in the database. |
| `IndiAllSkyDbVideoTable` | `video` | Nightly and daytime timelapse video records (`.mp4`). |
| `IndiAllSkyDbMiniVideoTable` | `minivideo` | Rolling mini-timelapses compiled over recent capture windows. |
| `IndiAllSkyDbKeogramTable` | `keogram` | Daily keogram image records. |
| `IndiAllSkyDbStarTrailsTable` | `startrail` | Cumulative star trail stacked frames. |
| `IndiAllSkyDbStarTrailsVideoTable` | `startrailvideo` | Progressive star trail accumulation videos. |
| `IndiAllSkyDbFitsImageTable` | `fitsimage` | Raw astronomical FITS frame metadata. |
| `IndiAllSkyDbRawImageTable` | `rawimage` | Uncompressed RAW / DNG capture records. |
| `IndiAllSkyDbPanoramaImageTable` | `panoramaimage` | Dewarped panoramic image projections. |
| `IndiAllSkyDbPanoramaVideoTable` | `panoramavideo` | Panoramic timelapse recordings. |
| `IndiAllSkyDbLongTermKeogramTable` | `longtermkeogram` | Multi-night and multi-month aggregated keograms. |
| `IndiAllSkyDbBadPixelMapTable` | `badpixelmap` | Calibration maps for defective sensor pixels. |
| `IndiAllSkyDbDarkFrameTable` | `darkframe` | Master dark frame calibration libraries categorized by exposure, gain, and temperature. |
| `IndiAllSkyDbTaskQueueTable` | `taskqueue` | IPC queue managing asynchronous tasks dispatched between web processes and the capture daemon. |
| `IndiAllSkyDbNotificationTable` | `notification` | User-facing system notifications and error alerts. |
| `IndiAllSkyDbStateTable` | `state` | Key-value store for live daemon operational state and metrics. |
| `IndiAllSkyDbUserTable` | `user` | User authentication records (Argon2 passwords, roles, and OIDC claims). |
| `IndiAllSkyDbTleDataTable` | `tledata` | Two-Line Element (TLE) satellite orbital data fetched from CelesTrak. |
| `IndiAllSkyDbConfigTable` | `config` | Camera configuration JSON documents. |

---

## 3. Inter-Process Communication (`taskqueue`)

Because the web application and the capture daemon execute as separate operating system processes, tasks such as pausing capture, generating on-demand keograms, rebuilding dark frames, or syncing files are coordinated via `IndiAllSkyDbTaskQueueTable`.

* **Queues (`TaskQueueQueue`)**: Dispatched to target processes (`MAIN`, `IMAGE`, `VIDEO`, `TRANSFER`).
* **States (`TaskQueueState`)**: Managed through states (`QUEUED`, `RUNNING`, `DONE`, `FAILED`, `MANUAL`).

---

## 4. Schema Migrations

Database schema changes are managed through Alembic and Flask-Migrate:
* Migration scripts reside in `migrations/versions/`.
* On Debian package updates, migrations execute automatically during package installation via `debian/postinst`.
* To manually execute pending migrations:
  ```bash
  # Debian Package Installations:
  sudo -u indi-allsky /var/lib/indi-allsky/venv/bin/flask --app indi_allsky.wsgi:app db upgrade head

  # Source / Git Installations:
  source /var/lib/indi-allsky/virtualenv/bin/activate
  flask --app indi_allsky.wsgi:app db upgrade head
  ```
  See [`Database Migrations`](Database-migrations.md) for full procedures and rollback steps.