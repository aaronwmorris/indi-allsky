# Converting from SQLite to MySQL / MariaDB

By default, `indi-allsky` utilizes SQLite operating in Write-Ahead Logging (`WAL`) mode. For single-camera installations, SQLite delivers superior read latency, lower memory overhead, and automated file-level backups.

Migrating to MariaDB or MySQL is recommended primarily for:
* Multi-camera cluster environments sharing a single database backend.
* High-write remote portal instances serving concurrent web traffic.
* External database replication architectures.

---

## 1. Prerequisites

1. Install and initialize MariaDB Server as documented in [MySQL & MariaDB Information](MySQL-MariaDB-Information).
2. Create the target database (`indi_allsky`) and grant permissions to the database user:
   ```sql
   CREATE DATABASE indi_allsky CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   GRANT ALL PRIVILEGES ON indi_allsky.* TO 'indi_allsky_own'@'localhost' IDENTIFIED BY 'your_password';
   FLUSH PRIVILEGES;
   ```

---

## 2. Conversion Workflow (Debian `.deb` Installations)

### Step 1: Stop Background Services
```bash
sudo systemctl stop indi-allsky.service gunicorn-indi-allsky.service
```

### Step 2: Update Database Connection String
Edit `/etc/indi-allsky/flask.json` and set the `SQLALCHEMY_DATABASE_URI`:
```json
"SQLALCHEMY_DATABASE_URI": "mysql+mysqlconnector://indi_allsky_own:your_password@localhost:3306/indi_allsky?charset=utf8mb4&collation=utf8mb4_unicode_ci"
```

### Step 3: Initialize Database Schema
Run the database migration to create the tables in the new MariaDB instance:
```bash
sudo /usr/share/indi-allsky/venv/bin/flask --app indi_allsky.wsgi db upgrade head
```

### Step 4: Migrate Data Records
Execute the data conversion utility to copy records from the SQLite file into MariaDB:
```bash
sudo indi-allsky-ctl convert-db
```
*(Depending on capture history and database size, this process may require several minutes).*

### Step 5: Validate Data Integrity
```bash
sudo indi-allsky-ctl validate-db
```

### Step 6: Restart Services
```bash
sudo systemctl start gunicorn-indi-allsky.service indi-allsky.service
```

---

## 3. Conversion Workflow (Source / Git / `setup.sh` Installations)

### Step 1: Stop Services
```bash
systemctl --user stop indi-allsky
```

### Step 2: Activate Virtual Environment
```bash
source /var/lib/indi-allsky/virtualenv/bin/activate
# Or from git root: source virtualenv/indi-allsky/bin/activate
```

### Step 3: Update `flask.json` & Run Migrations
Update `SQLALCHEMY_DATABASE_URI` in `/etc/indi-allsky/flask.json`, then apply migrations:
```bash
flask db upgrade head
```

### Step 4: Run Conversion Script
```bash
python ./misc/convert_db.py
```

### Step 5: Validate & Restart
```bash
python ./misc/validate_db_entries.py
systemctl --user start indi-allsky
```
