# SyncAPI: Forcing Full Media Re-Synchronization

The `indi-allsky` SyncAPI synchronization engine tracks whether a media asset has been uploaded to a remote portal instance via the `sync_id` integer column in each database table. When an asset is successfully transferred and registered with the remote portal, `sync_id` is populated with the remote record identifier.

Setting `sync_id = NULL` resets the synchronization status, causing `upload_sync` to re-transmit the selected media records.

---

## 1. Database Reset

Access the database console according to your configured database backend:

### SQLite Installations
```bash
sqlite3 -table -header /var/lib/indi-allsky/indi-allsky.sqlite
```

### MySQL / MariaDB Installations
```bash
mysql -u indi-allsky -p indi-allsky
```

---

## 2. Execute SQL Status Reset

### Reset Derived Media (Timelapses, Keograms, Star Trails)
To re-synchronize compiled daily assets without re-uploading millions of individual raw frames:

```sql
UPDATE video SET sync_id = NULL;
UPDATE minivideo SET sync_id = NULL;
UPDATE keogram SET sync_id = NULL;
UPDATE startrail SET sync_id = NULL;
UPDATE startrailvideo SET sync_id = NULL;
UPDATE panoramavideo SET sync_id = NULL;
```

### Reset Still Images (Optional)
> [!WARNING]
> Still image synchronization involves considerable network bandwidth and HTTP overhead. Re-syncing years of raw captures can take days. Restrict image updates by date range when possible.

```sql
-- Reset all images
UPDATE image SET sync_id = NULL;
UPDATE panoramaimage SET sync_id = NULL;

-- Or restrict reset to recent days (example: past 7 days in SQLite)
UPDATE image SET sync_id = NULL WHERE createDate >= datetime('now', '-7 days');
```

Exit the database client (`.quit` in SQLite or `exit` in MySQL).

---

## 3. Trigger Synchronization

### Debian Package (`.deb`) Installations
Execute the sync process using `indi-allsky-ctl`:

```bash
# Preview pending synchronization items
sudo indi-allsky-ctl retry-uploads report

# Execute synchronization for derived media
sudo indi-allsky-ctl retry-uploads sync

# Execute synchronization including still images (default lookback is 30 days)
sudo indi-allsky-ctl retry-uploads sync --upload-images --days 7 -t 2
```

### Source / Git (`setup.sh`) Installations
Activate the virtual environment and execute `upload_sync.py`:

```bash
source /var/lib/indi-allsky/virtualenv/bin/activate
# Or from git checkout: source virtualenv/indi-allsky/bin/activate

# Report pending sync items
python ./misc/upload_sync.py report

# Execute synchronization
python ./misc/upload_sync.py sync

# Execute synchronization with still images
python ./misc/upload_sync.py sync --upload-images --days 7 -t 2
```

### Command Options Reference
* `report`: Generates a formatted summary table detailing all unsynchronized records across tables.
* `sync`: Begins immediate sequential or multi-threaded synchronization.
* `-t`, `--threads`: Number of concurrent worker threads (default: `1`).
* `-d`, `--days`: Temporal lookback window in days for image records (default: `30`).
* `--upload-images`: Enables still image synchronization (disabled by default in CLI runs to conserve bandwidth).
* `--no-syncapi`: Bypasses SyncAPI transfers and focuses exclusively on external S3/FTP filetransfers.
