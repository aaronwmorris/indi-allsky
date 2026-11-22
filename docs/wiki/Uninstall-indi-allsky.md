# Uninstalling indi-allsky

Instructions for removing, purging, or disabling `indi-allsky` across both Debian package installations and legacy manual source checkouts.

---

## Option 1: APT Package Removal (Debian / Ubuntu / Raspberry Pi OS)

If you installed `indi-allsky` via the official APT repository (`apt.indi-allsky.org`):

### Remove Application (Preserve Configuration & Capture Data)
Removes the application binaries and services while leaving databases (`/var/lib/indi-allsky/`), configurations (`/etc/indi-allsky/`), and media libraries (`/var/www/html/allsky/`) intact:
```bash
sudo apt remove indi-allsky
```

### Complete Purge (Delete All Configuration & Data)
> [!CAUTION]
> Running `apt purge` permanently deletes all configuration files in `/etc/indi-allsky/`, SQLite databases in `/var/lib/indi-allsky/`, and system accounts.

```bash
sudo apt purge indi-allsky
```

---

## Option 2: Manual Source Uninstall (`setup.sh` Installs)

### 1. Stop and Disable Services
```bash
systemctl --user stop indi-allsky.service gunicorn-indi-allsky.socket gunicorn-indi-allsky.service indiserver.service
systemctl --user disable indi-allsky.service gunicorn-indi-allsky.socket gunicorn-indi-allsky.service indiserver.service
```

### 2. Remove User Systemd Units
```bash
rm -f "$HOME/.config/systemd/user/indiserver.service"
rm -f "$HOME/.config/systemd/user/indi-allsky.service"
rm -f "$HOME/.config/systemd/user/gunicorn-indi-allsky.socket"
rm -f "$HOME/.config/systemd/user/gunicorn-indi-allsky.service"
systemctl --user daemon-reload
```

### 3. Remove Web Server Virtual Hosts

#### Caddy (Default Reverse Proxy)
```bash
sudo rm -f /etc/caddy/caddy_indi-allsky.conf
sudo systemctl reload caddy
```

#### Nginx
```bash
sudo rm -f /etc/nginx/sites-enabled/indi-allsky.conf /etc/nginx/sites-available/indi-allsky.conf
sudo systemctl reload nginx
```

#### Apache
```bash
sudo a2dissite indi-allsky
sudo rm -f /etc/apache2/sites-available/indi-allsky.conf
sudo systemctl reload apache2
```

### 4. Remove Filesystem Data
```bash
# Images and media archives
sudo rm -rf /var/www/html/allsky

# SQLite database and migrations
sudo rm -rf /var/lib/indi-allsky

# Configuration and logs
sudo rm -rf /etc/indi-allsky /var/log/indi-allsky

# Source checkout
rm -rf "$HOME/indi-allsky"
```