# Migration Guide: Upgrading from `setup.sh` to `.deb` Package Architecture

This guide explains how existing installations created using `setup.sh` can migrate to the new `.deb` package architecture for `indi-allsky`.

---

## Key Architectural Differences

| Subsystem | Legacy `setup.sh` | New `.deb` Package Architecture |
| :--- | :--- | :--- |
| **System User** | User account running the script (e.g. `pi`, `allsky`) | Dedicated system user (`indi-allsky`) |
| **App Location** | `$HOME/indi-allsky` or clone folder | Standard `/usr/share/indi-allsky` |
| **Python Virtualenv** | `$HOME/virtualenv/indi-allsky` | System location `/var/lib/indi-allsky/venv` |
| **Configuration** | `/etc/indi-allsky/flask.json` | `/etc/indi-allsky/flask.json` (merged dynamically) |
| **Database File** | `/var/lib/indi-allsky/indi-allsky.sqlite` | `/var/lib/indi-allsky/indi-allsky.sqlite` (preserved) |
| **Systemd Units** | User units (`~/.config/systemd/user/`) | System units (`/lib/systemd/system/`) |

---

## Automated Migration Handling

When you install the `indi-allsky.deb` package using `sudo apt install ./indi-allsky.deb`, the post-installation script automatically handles the transition:

1. **User Service Cleanup**: Scans `/home/*/` for legacy user-level systemd timer/service units (`indi-allsky.service`, `indiserver.service`, `gunicorn-indi-allsky.socket`), disables them, and removes the unit files.
2. **Configuration Merge**: Preserves your existing `/etc/indi-allsky/flask.json` configuration, merging any new settings or placeholders from the release template while keeping your custom choices intact.
3. **Database Preservation**: Existing SQLite database files under `/var/lib/indi-allsky/` are retained and updated with new database migrations (`flask db upgrade`).
4. **Group Permissions**: Adds the new `indi-allsky` system user to all necessary hardware access groups (`dialout`, `video`, `plugdev`, `gpio`, `i2c`, `spi`, `adm`).

---

## Migration Steps for End Users

### Step 1: Stop Existing Legacy User Services
If your `setup.sh` service is currently running:
```bash
systemctl --user stop indi-allsky.service
systemctl --user stop gunicorn-indi-allsky.socket
systemctl --user stop indiserver.service
```

### Step 2: Install the `.deb` Package
```bash
sudo apt update
sudo apt install ./indi-allsky_*.deb
```

During installation, `debconf` will prompt you for any missing configuration parameters (camera interface, ports, admin credentials).

### Step 3: Verify the New Systemd Services
Check the status of the new system-level services:
```bash
sudo systemctl status indi-allsky.service
sudo systemctl status gunicorn-indi-allsky.service
sudo systemctl status indiserver.service
```

---

## Special Scenarios & INDI Driver Management

### Scenario A: Preserving Source-Built INDI (Custom Builds)
If you previously compiled INDI / drivers from source (e.g., using `setup.sh`'s source build or manual git builds) and want to ensure APT does not overwrite your custom binaries:

#### Option 1: Protect Before Install (from Existing Git Checkout)
From your existing `indi-allsky` git clone directory:
```bash
sudo bash misc/indi-allsky-ctl protect-source-indi
sudo apt install -y indi-allsky
```

#### Option 2: Lean Initial Install + Post-Install Protection
If you don't have the git checkout handy:
```bash
# 1. Install without downloading recommended driver packages
sudo apt install --no-install-recommends -y indi-allsky

# 2. Register source build so all future 'apt upgrade' runs are safe
sudo indi-allsky-ctl protect-source-indi
```

Both options register a local `indi-local-source` dummy package (version `99.0.0`) in the `dpkg` database that satisfies all INDI dependencies. APT will recognize your source build and will never overwrite your binaries in `/usr/bin` or `/usr/lib`.

---

### Scenario B: Pinning (Holding) Installed APT INDI Driver Versions
If you install INDI drivers via APT but want to guarantee that full system upgrades (`sudo apt upgrade`) do not touch or update your camera drivers:

1. **Pin (Hold) Drivers**:
   ```bash
   sudo indi-allsky-ctl hold-indi
   ```
2. **Check Pin Status**:
   ```bash
   indi-allsky-ctl status-indi-hold
   ```
3. **Unpin (Allow Upgrades)**:
   ```bash
   sudo indi-allsky-ctl unhold-indi
   ```

---

### Scenario C: Raspberry Pi HQ / Camera Module (Lean Install)
If you are using a native Raspberry Pi camera (`rpicam-apps` / `libcamera`) and do not want to download the 3rd-party USB camera driver bundle:
```bash
sudo apt install --no-install-recommends -y indi-allsky rpicam-apps
```
