# Camera Management: Hiding and Merging Camera Entries

When attaching new imaging hardware or after driver updates that alter camera naming strings, redundant camera profiles can accumulate in the web interface dropdown menu. This document details methods for concealing inactive profiles or merging duplicate records into a unified camera history.

---

## 1. Concealing Inactive Camera Entries

Camera visibility is governed by the boolean `hidden` column in the `camera` table. Setting this value to `1` (true) excludes the camera from the web user interface while preserving all historical data, images, and videos in the database.

> [!NOTE]
> If `indi-allsky` captures a new frame using a hidden camera profile, the daemon automatically resets `hidden = 0` to ensure active devices remain accessible.

### Step 1: Open Database Console

#### Debian Package (`.deb`) and Default SQLite Installations
```bash
sqlite3 -table -header /var/lib/indi-allsky/indi-allsky.sqlite
```

#### MySQL / MariaDB Installations
```bash
mysql -u indi-allsky -p indi-allsky
```

### Step 2: Query Camera Identifiers
```sql
SELECT id, name, friendlyName, hidden FROM camera;
```
Example output:
```text
+----+------------------+--------------+--------+
| id | name             | friendlyName | hidden |
+----+------------------+--------------+--------+
|  1 | CCD Simulator    |              |      0 |
|  2 | ZWO CCD ASI290MM |              |      0 |
+----+------------------+--------------+--------+
```

### Step 3: Flag Profile as Hidden
```sql
UPDATE camera SET hidden = 1 WHERE id = 1;
```

---

## 2. Merging Camera Entries (`merge-cameras`)

Upgrading INDI drivers (such as transitioning from `indi_asi_ccd` revisions or switching between driver architectures) may cause the driver to present a modified camera name (e.g., `ZWO CCD ASI290MM` to `ZWO ASI290MM`). This creates a secondary camera ID in `indi-allsky`, partitioning historical records across two dropdown choices.

The `merge-cameras` utility re-assigns all foreign-key relationships (images, raw frames, FITS files, timelapses, keograms, star trails, and thumbnails) from the duplicate ID to the primary camera ID. It also records the alternative name in the primary record (`name_alt1` or `name_alt2`) to prevent future duplication upon service restart.

### Debian Package (`.deb`) Installations
```bash
sudo indi-allsky-ctl merge-cameras -orig <ORIGINAL_CAMERA_ID> -n <NEW_CAMERA_ID>
```

### Source / Git (`setup.sh`) Installations
Activate the virtual environment and execute the script directly:
```bash
source /var/lib/indi-allsky/virtualenv/bin/activate
# Or from git checkout: source virtualenv/indi-allsky/bin/activate

python ./misc/merge_cameras.py -orig <ORIGINAL_CAMERA_ID> -n <NEW_CAMERA_ID>
```

* `-orig`, `--orig_camera_id`: The historical camera ID that should retain all historical imagery.
* `-n`, `--new_camera_id`: The newly generated camera ID whose records will be migrated into the original camera.