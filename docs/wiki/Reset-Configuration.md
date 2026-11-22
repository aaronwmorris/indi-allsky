# Reset Configuration to Defaults

Use these instructions to revert all camera configurations to their default initial values.

---

## Method 1: Debian Package Installations (`indi-allsky-ctl` — Recommended)

On installations managed via the `.deb` package / APT repository, you can reset configuration directly:

1. **Stop services:**
   ```bash
   sudo systemctl stop indi-allsky.service gunicorn-indi-allsky.service
   ```

2. *(Optional)* **Backup active configuration:**
   ```bash
   indi-allsky-ctl dump-config > indi_allsky_config_$(date +%Y%m%d_%H%M%S).json
   ```

3. **Reset configuration to defaults:**
   ```bash
   sudo indi-allsky-ctl reset-config
   ```
   *(Direct CLI alternative without `indi-allsky-ctl`: `/var/lib/indi-allsky/venv/bin/python /usr/share/indi-allsky/config.py flush --force && /var/lib/indi-allsky/venv/bin/python /usr/share/indi-allsky/config.py bootstrap`)*

4. **Restart services:**
   ```bash
   sudo systemctl start indi-allsky.service gunicorn-indi-allsky.service
   ```

---

## Method 2: Git / Source Installations

1. **Stop services:**
   ```bash
   systemctl --user stop indi-allsky
   systemctl --user stop gunicorn-indi-allsky
   ```

2. **Activate the Python virtual environment:**
   ```bash
   cd indi-allsky
   source virtualenv/indi-allsky/bin/activate
   ```

3. *(Optional)* **Backup active configuration:**
   ```bash
   ./config.py dump > indi_allsky_config_$(date +%Y%m%d_%H%M%S).json
   ```

4. **Flush and bootstrap initial configuration:**
   ```bash
   ./config.py flush --force
   ./config.py bootstrap
   ```

5. **Restart services:**
   ```bash
   systemctl --user start gunicorn-indi-allsky
   systemctl --user start indi-allsky
   ```