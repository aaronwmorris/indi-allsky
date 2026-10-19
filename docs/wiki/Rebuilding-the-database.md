# Database Integrity Checking & Reconstruction

When filesystem corruption, hardware power interruptions, or migrations corrupt the database engine, `indi-allsky` provides tools to diagnose integrity, repair malformed structures, or reconstruct the database schema from disk assets.

---

## 1. Integrity Verification & Low-Level Repair

### SQLite Integrity Audit
Execute `PRAGMA integrity_check` directly against the database file:

```bash
sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite "PRAGMA integrity_check;"
```
If the output is `ok`, the relational B-trees are physically sound. If errors appear (e.g. `database disk image is malformed`), proceed with SQL dump extraction.

### SQLite Dump Recovery
If the SQLite database exhibits structural errors, dumping surviving records into an ASCII SQL script often recovers all or most tabular data:

```bash
cd /var/lib/indi-allsky

# Export salvageable SQL statements
sqlite3 indi-allsky.sqlite ".dump" > /tmp/salvaged_indi-allsky.sql

# Isolate corrupted database files
sudo mkdir -p /var/lib/indi-allsky/corrupt_archive
sudo mv indi-allsky.sqlite* /var/lib/indi-allsky/corrupt_archive/

# Rebuild from SQL dump
sqlite3 indi-allsky.sqlite < /tmp/salvaged_indi-allsky.sql

# Verify physical structure of recovered database
sqlite3 indi-allsky.sqlite "PRAGMA integrity_check;"

# Fix filesystem permissions
sudo indi-allsky-ctl fix-perms
```

### MySQL / MariaDB Table Check & Optimization
```bash
sudo mysqlcheck -u root -p indi-allsky --analyze
sudo mysqlcheck -u root -p indi-allsky --repair

# Reclaim allocated table space using indi-allsky-ctl
sudo indi-allsky-ctl optimize-mysql
```

---

## 2. Clean Database Reconstruction from Filesystem Media

If database corruption is irreparable, or after migrating image folders to a new host, the database schema may be rebuilt from scratch and historical media indexed directly from disk.

### Step 1: Stop Services

#### Debian Package (`.deb`) Installations
```bash
sudo systemctl stop indi-allsky.service gunicorn-indi-allsky.service
```

#### Source / Git (`setup.sh`) Installations
```bash
# If using user-level systemd:
systemctl --user stop indi-allsky gunicorn-indi-allsky
# Or if using system-level services:
sudo systemctl stop indi-allsky.service gunicorn-indi-allsky.service
```

### Step 2: Purge Corrupted Database
```bash
sudo rm -f /var/lib/indi-allsky/indi-allsky.sqlite*
```

### Step 3: Initialize Schema & Default Configuration

#### Debian Package (`.deb`) Installations
```bash
# Execute Alembic migrations to current head
sudo -u indi-allsky /var/lib/indi-allsky/venv/bin/flask --app indi_allsky.wsgi:app db upgrade head

# Bootstrap default camera configuration
sudo indi-allsky-ctl reset-config
```

#### Source / Git (`setup.sh`) Installations
```bash
source /var/lib/indi-allsky/virtualenv/bin/activate
# Or from git checkout: source virtualenv/indi-allsky/bin/activate

flask --app indi_allsky.wsgi:app db upgrade head
python ./config.py bootstrap
```

### Step 4: Re-Index Existing Media Files
Run the media ingestion routine to scan the image folder and generate database records for all existing images, timelapses, keograms, and star trails:

#### Debian Package (`.deb`) Installations
```bash
sudo -u indi-allsky /var/lib/indi-allsky/venv/bin/python /usr/share/indi-allsky/allsky.py dbImportImages
```

#### Source / Git (`setup.sh`) Installations
```bash
python ./allsky.py dbImportImages
```
*Prompt: Enter the camera name when requested (e.g., `ZWO CCD ASI290MM` or `libcamera_imx477`).*

### Step 5: Regenerate Thumbnails and Re-Import Calibration Darks

#### Debian Package (`.deb`) Installations
```bash
# Regenerate missing thumbnails
sudo indi-allsky-ctl rebuild-thumbnails

# Re-import dark frames and bad pixel maps from disk
sudo indi-allsky-ctl import-darks
```

#### Source / Git (`setup.sh`) Installations
```bash
python ./misc/create_thumbnails.py
python ./misc/import_darks_frames.py
```

### Step 6: Restart Services
```bash
# Debian Package:
sudo systemctl start gunicorn-indi-allsky.service indi-allsky.service

# Source / Git Checkout:
systemctl --user start gunicorn-indi-allsky indi-allsky
```

---

## 3. Extracting and Restoring Configuration from Backup

Database backups created via `indi-allsky-ctl backup-db` (or scheduled maintenance) reside in `/var/lib/indi-allsky/backup/`.

### Inspect and Extract Archived Configuration
```bash
# Uncompress backup to a temporary database
gunzip -c /var/lib/indi-allsky/backup/backup_YYYYMMDD_HHMMSS.sql.gz | sqlite3 /tmp/restore_temp.sqlite

# List configuration revisions stored in backup
sqlite3 /tmp/restore_temp.sqlite -header -table "SELECT id, level, note, createDate FROM config ORDER BY createDate DESC;"

# Extract configuration JSON for a target ID (e.g. ID 5)
sqlite3 /tmp/restore_temp.sqlite "SELECT data FROM config WHERE id=5;" | jq . > /tmp/extracted_config.json
```

### Apply Extracted Configuration to Active System

#### Debian Package (`.deb`) Installations
```bash
sudo indi-allsky-ctl config load --config /tmp/extracted_config.json --force
```

#### Source / Git (`setup.sh`) Installations
```bash
python ./config.py load --config /tmp/extracted_config.json --force
```