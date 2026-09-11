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

### Flush Camera Images & Videos from Database
Purge all image records (and optionally video records) associated with a specific camera ID from the database:
```bash
sudo indi-allsky-ctl flush-images --camera_id 1
# Include videos as well:
sudo indi-allsky-ctl flush-images --camera_id 1 --flush-videos
# Alias:
sudo indi-allsky-ctl purge-images --camera_id 1
```

### Flush Recent Images (Last 16 Minutes)
Flush images taken in the last 16 minutes from the database to reset recent exposure/gain/bin adaptation heuristics without clearing full history:
```bash
sudo indi-allsky-ctl flush-16min-images
# Alias:
sudo indi-allsky-ctl flush-recent-images
```

### Merge Camera Entries
When upgrading INDI driver versions or switching camera configurations, a camera may be assigned a new database ID. Merge historical records and images from the old camera entry to the new one:
```bash
sudo indi-allsky-ctl merge-cameras -orig <old_camera_id> -n <new_camera_id>
```

### Optimize MySQL / MariaDB Database
Analyze and reclaim unused storage space across all `indi_allsky` MySQL tables:
```bash
sudo indi-allsky-ctl optimize-mysql
# Alias:
sudo indi-allsky-ctl mysql-optimize
```
*(Ensure `indi-allsky` service is stopped before optimizing tables).*

### Import Dark Frames & Bad Pixel Maps
Interactively import pre-existing dark calibration frames and bad pixel maps into the database:
```bash
sudo indi-allsky-ctl import-darks
```

### Retry / Sync Pending Uploads
Manually trigger synchronization of pending or failed uploads (SFTP, S3, Sync API) for images and videos:
```bash
# Display upload sync report:
indi-allsky-ctl retry-uploads report

# Run synchronization:
indi-allsky-ctl retry-uploads sync --days 30 --threads 2

# Aliases:
indi-allsky-ctl upload-sync sync
indi-allsky-ctl sync-uploads sync
```

### Add System Alert Notification
Inject a user notification directly into the database to display in the web interface notification center:
```bash
indi-allsky-ctl notify <CATEGORY> <ITEM> <MESSAGE> <EXPIRE_MINUTES>

# Example:
indi-allsky-ctl notify GENERAL "Maintenance" "Scheduled system reboot in 10 minutes" 60
```
*Categories:* `GENERAL`, `MISC`, `MEDIA`, `HARDWARE`, `CAMERA`, etc.

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

### Detailed Camera Information
Connect to the running INDI server and print a detailed summary table of sensor parameters, gain ranges, resolutions, pixel dimensions, and supported video formats:
```bash
indi-allsky-ctl camera-info
```

### Inspect Camera Properties
Dump all INDI driver properties, controls, switches, and exposed parameters for attached camera devices:
```bash
indi-allsky-ctl camera-props
# Alias:
indi-allsky-ctl camera-properties
```

### Test Camera Linearity
Measure camera sensor linearity across progressive exposure times:
```bash
indi-allsky-ctl test-linearity -C 3 -M 1.0 -m 0.01 -g 100 -l 25
# Alias:
indi-allsky-ctl camera-linearity -C 3 -M 1.0
```
*Options:*
* `-C, --Count`: Number of exposures per level (default: 3)
* `-M, --Max_exposure`: Maximum exposure in seconds (default: 1.0)
* `-m, --min_exposure`: Minimum exposure in seconds
* `-g, --gain`: Camera gain to test
* `-l, --level`: Exposure increment step percentage (default: 25%)
* `--calibrate`: Enable dark calibration subtraction during test

### Test Environmental Sensors
Probe configured I2C, SPI, 1-Wire, and serial hardware sensors (e.g. BME280, BMP280, INA219, MLX90614) and display live telemetry readings:
```bash
indi-allsky-ctl test-sensors
```

### Test Fans, Heaters & GPIO Devices
Test auxiliary hardware controllers such as enclosure fans, dew heaters, and GPIO outputs:
```bash
# Test fan operation:
indi-allsky-ctl test-devices fan

# Test dew heater operation:
indi-allsky-ctl test-devices dew_heater

# Test automatic GPIO pins:
indi-allsky-ctl test-devices auto_gpio

# Aliases:
indi-allsky-ctl test-fans fan
indi-allsky-ctl test-hardware dew_heater
```

### Test Upload Protocols
Validate configured file transfer destinations and cloud storage connections:
```bash
# Test SFTP / FTP transfers:
indi-allsky-ctl test-upload filetransfer

# Test S3 / Object Storage:
indi-allsky-ctl test-upload s3

# Test Sync API endpoint:
indi-allsky-ctl test-upload syncapi
```

### Test ADS-B Aircraft Tracking
Validate dump1090 connection and inspect live aircraft tracking data:
```bash
indi-allsky-ctl test-adsb
```

### Test Oracle Cloud (OCI) Configuration
Verify that the configured OCI credentials file and API keys are valid:
```bash
indi-allsky-ctl test-oci
```

### Test WebSocket Events & Remote Actions
Connect to the real-time WebSocket event stream or send immediate action commands:
```bash
# Interactive listener mode (listens for events and accepts interactive commands):
indi-allsky-ctl test-websocket

# Send a single control action:
indi-allsky-ctl test-websocket --action pause
indi-allsky-ctl test-websocket --action ping
indi-allsky-ctl test-websocket --action get_status
indi-allsky-ctl test-websocket --action keogram

# Aliases:
indi-allsky-ctl test-ws --action ping
```

### Generate Diagnostic Support Bundle
Generate a redacted diagnostic report containing system logs, hardware configurations, and environment details for troubleshooting:
```bash
sudo indi-allsky-ctl support-info
```

---

## 4. Peripheral Configuration & Integrations

Interactive setup helpers for common hardware accessories and integrations:

### Disable Raspberry Pi Onboard LEDs
Disable status, power, and ethernet LEDs on Raspberry Pi 3, 4, or 5 to eliminate stray dome reflections:
```bash
sudo indi-allsky-ctl disable-leds
# Alias:
sudo indi-allsky-ctl setup-leds
```

### Setup Mosquitto MQTT Broker
Install and configure the local Mosquitto MQTT message broker:
```bash
indi-allsky-ctl setup-mqtt
# Alias:
indi-allsky-ctl setup-mosquitto
```
*(Run as your normal user with sudo privileges; do not run directly as root).*

### Home Assistant MQTT Auto-Discovery
Publish Home Assistant auto-discovery MQTT payloads so all camera sensors, temperatures, and status indicators immediately populate in Home Assistant:
```bash
indi-allsky-ctl ha-discovery
# With custom device topic prefix:
indi-allsky-ctl ha-discovery --device_topic allsky
# Alias:
indi-allsky-ctl setup-ha-discovery
```

### Setup GPS / GPSD
Configure `gpsd` and serial GPS receivers for hardware time synchronization:
```bash
sudo indi-allsky-ctl setup-gps
```

### Setup WiFi Hotspot Failover
Set up automatic WiFi hotspot fallback using NetworkManager when home WiFi is unreachable:
```bash
sudo indi-allsky-ctl setup-hotspot
```

### Setup Hardware RTC (Real-Time Clock)
Configure an I2C DS3231 or PCF8563 real-time clock module:
```bash
sudo indi-allsky-ctl setup-rtc
```

### Setup USB Drive Automount
Configure `udisks2` rules to automatically mount external USB flash storage:
```bash
sudo indi-allsky-ctl setup-usb-mount
```

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
# Alias:
sudo indi-allsky-ctl unpin-indi
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
* [Home Assistant & MQTT Integration](MQTT-Broker-Publishing)
* [Dark Calibration Frames](Dark-Calibration-Frames)
* [ADS-B Aircraft Tracking](ADS‐B-Aircraft-Tracking)
* [Disable LEDs](Disable-LEDs)
* [Miscellaneous Tools Directory](Misc-Folder)
