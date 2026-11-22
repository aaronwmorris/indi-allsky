# `indi_pylibcamera` Driver Setup

`indi_pylibcamera` is a Python-based INDI driver that interfaces with Raspberry Pi libcamera CSI sensors (IMX477 HQ Camera, IMX708 Camera Module 3, IMX296 Global Shutter Camera) via the official Python bindings (`python3-picamera2` and `python3-libcamera`).

> [!IMPORTANT]
> **Debian Package (`.deb`) Installations**: The pre-built `.deb` package installs all necessary system libraries and manages systemd units automatically. Modifying `pyvenv.cfg` or executing `pip install` inside `/var/lib/indi-allsky/venv/` is unnecessary and unsupported.
>
> The setup steps below apply specifically to **Source / Git Checkout (`setup.sh`)** installations configuring user-level INDI servers (`systemctl --user`).

---

## 1. System Requirements

* **Operating System**: Raspberry Pi OS 12 (Bookworm) 64-bit or Raspberry Pi OS 13 (Trixie) 64-bit.
* **Memory**: Minimum 2 GB RAM recommended due to Python runtime memory consumption during frame acquisition and debayering.

---

## 2. Install Host Dependencies

Install the system Python libcamera bindings:

```bash
sudo apt-get update
sudo apt-get install -y \
    python3-picamera2 \
    python3-libcamera \
    libgles2-mesa
```

---

## 3. Virtual Environment Configuration (Source Installs Only)

Python `libcamera` bindings must be inherited from system site-packages.

### Step 1: Enable System Site Packages
Edit the virtual environment configuration file (`virtualenv/indi-allsky/pyvenv.cfg`):

```ini
home = /usr/bin
include-system-site-packages = true
version = 3.11.2
executable = /usr/bin/python3.11
```

### Step 2: Install Driver inside Virtualenv
Activate the virtual environment and install `indi-pylibcamera`:

```bash
source /var/lib/indi-allsky/virtualenv/bin/activate
# Or from git checkout: source virtualenv/indi-allsky/bin/activate

pip3 install indi-pylibcamera
pip3 install --upgrade simplejpeg
```

---

## 4. User Systemd Unit Configuration

When executing `indiserver` under a user systemd service (`$HOME/.config/systemd/user/indiserver.service`), ensure `PATH` and `PYTHONPATH` expose the virtualenv and system libraries:

```ini
[Unit]
Description=INDI Server
After=network.target

[Service]
Environment="PATH=/home/pi/indi-allsky/virtualenv/indi-allsky/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONPATH=/home/pi/indi-allsky/virtualenv/indi-allsky/lib/python3.11/site-packages:/usr/local/lib/aarch64-linux-gnu/python3.11/site-packages"
ExecStart=/usr/bin/indiserver -p 7624 indi_simulator_telescope indi_pylibcamera
ExecStop=/bin/kill -TERM $MAINPID
Restart=on-failure
RestartSec=5
PrivateTmp=true
UMask=0022

[Install]
WantedBy=default.target
```

Reload and restart the user service:
```bash
systemctl --user daemon-reload
systemctl --user restart indiserver
systemctl --user status indiserver
```

---

## 5. Driver Configuration Preset

In the web interface under **Camera Settings -> INDI Custom Properties / Switches**:

```json
{
    "SWITCHES": {
        "CAMCTRL_AWBENABLE": {
            "on": [
                "INDI_ENABLED"
            ],
            "off": []
        }
    },
    "PROPERTIES": {},
    "TEXT": {}
}
```

Reference repository: [scriptorron/indi_pylibcamera](https://github.com/scriptorron/indi_pylibcamera)