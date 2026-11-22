# Database Migrations

`indi-allsky` uses [Flask-Migrate](https://flask-migrate.readthedocs.io/) and [Alembic](https://alembic.sqlalchemy.org/) to track and apply database schema changes across updates.

---

## 1. Automated Migrations (Debian `.deb` Installations)

For installations managed via the official APT repository (`apt.indi-allsky.org`), database schema migrations execute **automatically** during package installation and updates (`indi-allsky.postinst`).

Manual intervention is not required during regular package upgrades.

To manually trigger or verify pending migrations on a Debian package installation:
```bash
sudo /var/lib/indi-allsky/venv/bin/flask --app indi_allsky.wsgi db upgrade head
```

---

## 2. Manual Migrations (Source / Git / `setup.sh` Installations)

When updating source installations via git:

1. Stop the background capture service:
   ```bash
   systemctl --user stop indi-allsky
   ```
2. Activate the Python virtual environment:
   ```bash
   source /var/lib/indi-allsky/virtualenv/bin/activate
   # Or from git root: source virtualenv/indi-allsky/bin/activate
   ```
3. Backup the database file:
   ```bash
   cp /var/lib/indi-allsky/indi-allsky.sqlite /var/lib/indi-allsky/backup_pre_upgrade.sqlite
   ```
4. Apply the latest database migrations:
   ```bash
   flask db upgrade head
   ```
5. Restart the service:
   ```bash
   systemctl --user start indi-allsky
   ```

---

## 3. SQLite Backup & Restoration

The primary SQLite database resides at `/var/lib/indi-allsky/indi-allsky.sqlite`.

### Online Safe Backup (Hot Backup)
To create an atomic, non-locking backup while the daemon is actively capturing:
```bash
sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite ".backup '/var/lib/indi-allsky/backup_$(date +%Y%m%d_%H%M%S).sqlite'"
gzip /var/lib/indi-allsky/backup_*.sqlite
```

### Portable SQL Dump (Cross-Platform)
To create an architecture-independent text dump:
```bash
sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite .dump | gzip -c > /var/lib/indi-allsky/indi-allsky_dump.sql.gz
```

### Restoring from Backup
1. Stop the daemon:
   * Debian `.deb`: `sudo systemctl stop indi-allsky`
   * Source: `systemctl --user stop indi-allsky`
2. Replace or restore the database file:
   ```bash
   gunzip -c /var/lib/indi-allsky/backup_20261016.sqlite.gz > /var/lib/indi-allsky/indi-allsky.sqlite
   ```
3. Verify permissions:
   ```bash
   sudo chown indi-allsky:indi-allsky /var/lib/indi-allsky/indi-allsky.sqlite
   sudo chmod 660 /var/lib/indi-allsky/indi-allsky.sqlite
   ```
4. Restart the daemon.

---

## 4. Recovering from Desynchronized Migrations

If a git update causes the database schema revision to fall out of synchronization with local migration files (e.g., `Can't locate revision xxxxxxxxxxxx`):

1. Inspect the recorded Alembic version:
   ```bash
   sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite "SELECT * FROM alembic_version;"
   ```
2. Stamp the database to the current head revision:
   * **Debian Package Installations**:
     ```bash
     sudo /var/lib/indi-allsky/venv/bin/flask --app indi_allsky.wsgi db stamp head
     ```
   * **Source Installations**:
     ```bash
     flask db stamp head
     ```