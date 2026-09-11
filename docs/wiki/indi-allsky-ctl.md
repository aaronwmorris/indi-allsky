# Command-Line Utility: `indi-allsky-ctl`

`indi-allsky-ctl` is the unified command-line control and maintenance utility for `indi-allsky`. Installed automatically at `/usr/bin/indi-allsky-ctl` with the `.deb` package, it wraps common maintenance tasks, service operations, hardware diagnostics, and database utilities into a single command without requiring you to manually activate python virtual environments or remember script paths.

---

## Quick Reference

```bash
indi-allsky-ctl <command> [options/arguments...]
```

To see all available commands from the terminal:
```bash
indi-allsky-ctl --help
```

---

## 1. User & Authentication Management

Manage web interface user accounts directly from the command line:

### List Users
List all active and inactive web users, their admin status, and contact info:
```bash
indi-allsky-ctl user-list
```

### Reset / Change Password
Change or reset the password for an existing web account:
```bash
sudo indi-allsky-ctl passwd -u <username>
# Or alias:
sudo indi-allsky-ctl reset-pass -u <username>
```

### Add a New User
Create a new user account with administrative privileges:
```bash
sudo indi-allsky-ctl user-add -u <username> -p <password> -n "Full Name" -e "user@example.com" --admin
```
*(Omit `--admin` for a standard view-only account).*

### Delete a User
Remove a user account:
```bash
sudo indi-allsky-ctl user-del -u <username>
```

---

## 2. Database & Storage Management

### Immediate Database Backup
Create an immediate gzipped SQLite database backup inside `/var/lib/indi-allsky/backup/`:
```bash
sudo indi-allsky-ctl backup-db
```

### Repair File & Directory Permissions
Recursively verify and repair ownership and permissions across all system and web directories (`/var/log/indi-allsky`, `/etc/indi-allsky`, `/var/lib/indi-allsky`, `/var/www/html/allsky`, and your active `IMAGE_FOLDER`):
```bash
sudo indi-allsky-ctl fix-perms
# Alias:
sudo indi-allsky-ctl repair-perms
```
> [!TIP]
> Use this command if you have manually copied images, darks, or config files with `sudo` or non-standard permissions and the web interface or capture daemon cannot write to them.

### Rebuild Missing Thumbnails
Scan your historical image collection and generate any missing thumbnails for timelapses, keograms, and startrails:
```bash
sudo indi-allsky-ctl rebuild-thumbnails
```

### Expire Images & Purge Old Files
Manually trigger image retention policies and delete expired captures:
```bash
sudo indi-allsky-ctl expire-images
```

### Audit & Validate Database
Check the integrity of image, timelapse, and keogram records against files on disk, fixing orphaned or broken database entries:
```bash
sudo indi-allsky-ctl validate-db
```

### Convert Database (SQLite to MySQL)
Migrate database records from SQLite to a MySQL/MariaDB server:
```bash
sudo indi-allsky-ctl convert-db
```

---

## 3. Hardware & Diagnostics

### Diagnostic Camera Test
Probe your configured camera interface and take a diagnostic test exposure:
```bash
indi-allsky-ctl test-camera
```

### List Detected INDI Cameras
Scan the local INDI server and list all detected camera devices:
```bash
indi-allsky-ctl list-cameras
```

### Test Environmental Sensors
Probe configured I2C, SPI, 1-Wire, and serial hardware sensors (e.g. BME280, BMP280, INA219, MLX90614) and display live telemetry readings:
```bash
indi-allsky-ctl test-sensors
```

### Generate Diagnostic Support Bundle
Generate a redacted diagnostic report containing system logs, hardware configurations, and environment details for troubleshooting:
```bash
sudo indi-allsky-ctl support-info
```

---

## 4. Peripheral Configuration Helpers

Interactive setup helpers for common hardware accessories:

* **Setup GPS / GPSD**:
  ```bash
  sudo indi-allsky-ctl setup-gps
  ```
  Configures `gpsd` and serial GPS receivers for hardware time synchronization.
* **Setup WiFi Hotspot Failover**:
  ```bash
  sudo indi-allsky-ctl setup-hotspot
  ```
  Sets up automatic WiFi hotspot fallback using NetworkManager when home WiFi is unreachable.
* **Setup Hardware RTC (Real-Time Clock)**:
  ```bash
  sudo indi-allsky-ctl setup-rtc
  ```
  Configures an I2C DS3231 or PCF8563 real-time clock module.
* **Setup USB Drive Automount**:
  ```bash
  sudo indi-allsky-ctl setup-usb-mount
  ```
  Configures `udisks2` rules to automatically mount external USB flash storage.

---

## 5. Package & Driver Management (INDI)

Prevent upstream package updates from inadvertently replacing working camera drivers:

### Pin (Hold) INDI Packages
Lock installed INDI packages (`indi-bin`, `indi-3rdparty`, `libindi*`) so that system-wide `apt upgrade` will not touch them:
```bash
sudo indi-allsky-ctl hold-indi
# Alias:
sudo indi-allsky-ctl pin-indi
```

### Unpin (Unhold) INDI Packages
Release the hold on INDI packages to allow them to upgrade normally:
```bash
sudo indi-allsky-ctl unhold-indi
```

### Check Hold Status
View which INDI packages are currently held:
```bash
indi-allsky-ctl status-indi-hold
```

### Protect Custom Source-Built INDI
If you compiled INDI or INDI 3rd-party drivers from source, register your build in the APT database using an equivs dummy package (`indi-local-source` version `99.0.0`):
```bash
sudo indi-allsky-ctl protect-source-indi
```
> [!NOTE]
> This satisfies all APT package dependencies without allowing package managers to overwrite your custom compiled binaries.

---

## 6. Service Control & Logs

### View Service Status
Check the status of `indi-allsky.service` and `gunicorn-indi-allsky.service`:
```bash
indi-allsky-ctl status
```

### Restart Services
Restart both the capture daemon and web server:
```bash
indi-allsky-ctl restart
```

### Stream Live Logs
Follow real-time systemd journal logs from both `indi-allsky` and `gunicorn`:
```bash
indi-allsky-ctl logs
```

---

## See Also
* [Backup and Recovery](Backup-and-Recovery)
* [Password Management](Web-Interface-Password)
* [Upgrading indi-allsky](Updating-indi-allsky)
* [Debian Deployment Workflow](Debian-Deployment-Workflow)
