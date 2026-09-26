# Overview
indi-allsky has a significant set of library requirements.  Not every package that is installed is needed in all cases, however, they are installed as a precaution.  In some cases where pre-compiled Python wheels are not available for a platform, the Python pip tool may attempt to compile python modules from source.

## Recommendations
| Component             | Recommendation  | Minimum | Note |
| --------------------- | --------------- | ------- | ---- |
| Single board computer | Raspberry Pi 4+<br>Any SBC with 2+GB of RAM | Raspberry Pi 3 | |
| Mini PC               | Any modern Intel/AMD processor<br>Most Virtualization Platforms | | |
| Platform              | 64-bit (`arm64`, `amd64`) | 64-bit  | 32-bit platforms lack required scientific Python wheels |
| OS                    | Raspberry Pi OS 12/13, Debian 12/13, Ubuntu 24.04/26.04 | Ubuntu 22.04 / Debian 12 | 64-bit distributions recommended |
| CPUs                  | 2+              | 1       | |
| RAM                   | 2+ GB           | 1 GB    | |
| Storage               | 256GB           | 64GB    | |

> [!WARNING]
> **32-bit Platforms (`armhf`, `x86`)**:
> 32-bit builds are unsupported due to upstream Python dependencies (`pyarrow`, `dask-image`) lacking 32-bit binary wheels. A 64-bit operating system (`arm64` / `amd64`) is strongly recommended.

---

## System Preparation

Before proceeding with the installation, ensure your system timezone and locales are properly configured. Accurate system timezone and time synchronization are essential for astronomical calculations (sun/moon positions, day/night transitions, and exposure scheduling).

### 1. Set System Timezone
Verify and set your local timezone using `timedatectl`:
```bash
# Check current status
timedatectl status

# Set your timezone (e.g., America/New_York, Europe/London, Australia/Sydney)
sudo timedatectl set-timezone <Region/City>
```
*(Raspberry Pi users can also use `sudo raspi-config` -> Localisation Options -> Timezone)*

### 2. Configure System Locales

Generate your preferred locales (e.g. en_US.UTF-8 or en_GB.UTF-8):

``` bash
# Multiple selections are allowed
sudo dpkg-reconfigure locales
```
*(Raspberry Pi users can also use `sudo raspi-config` -> Localisation Options -> Locale)*

---

## Option 1: Official APT Repository (Recommended)

The recommended installation method for Raspberry Pi OS, Debian, and Ubuntu is via the official APT repository at [`apt.indi-allsky.org`](https://apt.indi-allsky.org/). Pre-built `.deb` packages bundle all dependencies, Python virtual environments, and consolidated INDI camera drivers for an automated installation.

> [!TIP]
> Installing via `apt` takes less than 1 minute and automatically manages dependencies, upgrades, and systemd services.

### 1. Add GPG Keyring
```bash
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.indi-allsky.org/key.gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/indi-allsky.gpg
sudo chmod a+r /etc/apt/keyrings/indi-allsky.gpg
```

### 2. Add Repository Source (DEB822 format)
```bash
sudo tee /etc/apt/sources.list.d/indi-allsky.sources <<EOF
Types: deb
URIs: https://apt.indi-allsky.org
Suites: $(lsb_release -cs)
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/indi-allsky.gpg
EOF
```

> [!NOTE]
> To use bleeding-edge nightly builds, set `Components: nightly` in the `.sources` file above, or visit the [APT Web Portal](https://apt.indi-allsky.org/) to toggle release channels.

### 3. Install indi-allsky
```bash
sudo apt update
sudo apt install -y indi-allsky
```

> [!TIP]
> To choose a reverse proxy (Default is Caddy), add `apache2` or `nginx` to the `apt install` command.

During installation, an interactive setup wizard will guide you through configuring your camera driver, administrator credentials, and observatory coordinates.

---

## Option 2: Manual Source Installation (`setup.sh`)

For development environments or unsupported platforms, you can clone the git repository and run the setup script:

> [!CAUTION]
> Installing via `setup.sh` requires compiling INDI and Python wheels from source, which can take from 20 minutes to several hours depending on your hardware.

> [!NOTE]
> Existing systems previously installed using `setup.sh` can migrate cleanly to official `.deb` packages with all configuration and database history preserved. See the [Migration Guide](Setup-to-Deb-Migration).

1. (Optional) Setup locales:
   ```bash
   sudo dpkg-reconfigure locales
   ```

2. Install git:
   ```bash
   sudo apt-get update
   sudo apt-get install -y git
   ```

3. Clone the git repository:
   ```bash
   git clone https://github.com/aaronwmorris/indi-allsky.git
   cd indi-allsky/
   ```

4. Run `setup.sh` to install the system:
   ```bash
   ./setup.sh
   ```

5. Start the software:
   ```bash
   systemctl --user start indi-allsky
   ```

6. Open the web interface: `https://<device-ip>/` (or `https://raspberrypi.local/`).

---

## INDI Requirements

> [!NOTE]
> When using **Option 1 (APT Repository)**, INDI Core and all consolidated 3rd-party camera drivers (ZWO ASI, QHY, Player One, SVBony, ToupTek, etc.) are pre-compiled and bundled automatically. No manual INDI compilation is required.

If you are using **Option 2 (Manual Source Installation)**, INDI must be compiled using the bundled build script:

```bash
./misc/build_indi.sh
```
indi-allsky includes a script for compiling INDI from source.  The script is completely self-contained and automated.

`./misc/build_indi.sh`

The script requires an Internet connection to download packages and the source from GitHub.

| System             | Time           | Notes |
| ------------------ | -------------- | ----- |
| Modern PC          | 10-20 minutes  |       |
| Raspberry Pi 5     | 10-20 minutes  | Active cooling |
| Raspberry Pi 4 4GB | 40 minutes     | Requires more time if you do not have a fan/heatsink |
| Raspberry Pi 3 1GB | 3-4 hours      |       |

#### libcamera only build
If you plan on using a libcamera supported camera module, you only need to compile the core INDI library (without the 3rd party libraries and drivers).  **This can reduce your compile time by 50%**

**WARNING**: If you do this, the 3rd party indiserver drivers for ZWO, Player One, Touptek, etc will **NOT** be built.


## indiserver-only Install

An indiserver-only installation deploys the INDI driver server and camera drivers on a remote single-board computer or dedicated camera node, without the `indi-allsky` capture process or web interface.

### Option 1: Official APT Repository (In Progress)

> [!NOTE]
> Direct APT repository packaging for indiserver-only deployments is currently in progress. Please use **Option 2** (`indiserver_only_setup.sh`) below for standalone indiserver setups in the meantime.

1. Add GPG Keyring:
   ```bash
   sudo mkdir -p /etc/apt/keyrings
   curl -fsSL https://apt.indi-allsky.org/key.gpg | \
     sudo gpg --dearmor -o /etc/apt/keyrings/indi-allsky.gpg
   sudo chmod a+r /etc/apt/keyrings/indi-allsky.gpg
   ```

2. Add Repository Source (DEB822 format):
   ```bash
   sudo tee /etc/apt/sources.list.d/indi-allsky.sources <<EOF
   Types: deb
   URIs: https://apt.indi-allsky.org
   Suites: $(lsb_release -cs)
   Components: stable
   Architectures: $(dpkg --print-architecture)
   Signed-By: /etc/apt/keyrings/indi-allsky.gpg
   EOF
   ```

3. Install indiserver & drivers:
   ```bash
   sudo apt update
   sudo apt install -y indi-bin indi-3rdparty
   ```

### Option 2: Manual Source Installation (`indiserver_only_setup.sh`)

1. Install git:
   ```bash
   sudo apt-get update
   sudo apt-get install -y git
   ```

2. Clone the git repository:
   ```bash
   git clone https://github.com/aaronwmorris/indi-allsky.git
   cd indi-allsky/
   ```

3. Run `indiserver_only_setup.sh` to install indiserver:
   ```bash
   ./misc/indiserver_only_setup.sh
   ```

   > [!NOTE]
   > The setup script will inform you if you are required to build the INDI software from source using `./misc/build_indi.sh`.

### Manual Operation

1. Stop indi-allsky service:
   ```bash
   systemctl --user stop indi-allsky
   ```

2. Activate the indi-allsky Python virtual environment:
   ```bash
   source virtualenv/indi-allsky/bin/activate
   ```

3. Start indi-allsky:
   ```bash
   ./allsky.py run
   ```


## Services

The indi-allsky system consists of three services:

| Service    | systemd              | Purpose |
| ---------- | -------------------- | ------- |
| Capture    | indi-allsky          | Responsible for taking images, generating timelapses, and file transfers |
| indiserver | indiserver           | Manages the camera hardware |
| Web Server | gunicorn-indi-allsky | Web interface |


## Web-only install

The web-only install is intended for remote configuration to use the [SyncAPI](https://github.com/aaronwmorris/indi-allsky/wiki/SyncAPI-Setup) on a VPS or central server where no camera is directly connected.

### Option 1: Official APT Repository (Recommended)

1. Add GPG Keyring:
   ```bash
   sudo mkdir -p /etc/apt/keyrings
   curl -fsSL https://apt.indi-allsky.org/key.gpg | \
     sudo gpg --dearmor -o /etc/apt/keyrings/indi-allsky.gpg
   sudo chmod a+r /etc/apt/keyrings/indi-allsky.gpg
   ```

2. Add Repository Source (DEB822 format):
   ```bash
   sudo tee /etc/apt/sources.list.d/indi-allsky.sources <<EOF
   Types: deb
   URIs: https://apt.indi-allsky.org
   Suites: $(lsb_release -cs)
   Components: stable
   Architectures: $(dpkg --print-architecture)
   Signed-By: /etc/apt/keyrings/indi-allsky.gpg
   EOF
   ```

3. Install `indi-allsky-web`:
   ```bash
   sudo apt update
   sudo apt install -y indi-allsky-web
   ```

> [!TIP]
> `indi-allsky-web` provides the Flask dashboard, Gunicorn application server, and web server configuration for remote sync portals without requiring local camera hardware or INDI drivers.

### Option 2: Manual Source Installation (`web_only_setup.sh`)

1. Install git:
   ```bash
   sudo apt-get update
   sudo apt-get install -y git
   ```

2. Clone the git repository:
   ```bash
   git clone https://github.com/aaronwmorris/indi-allsky.git
   cd indi-allsky/
   ```

3. Run `web_only_setup.sh` to install the web interface:
   ```bash
   ./misc/web_only_setup.sh
   ```

4. Login to the indi-allsky web application:
   `https://<device-ip>/` (or `https://hostname/`)

   > [!NOTE]
   > The web server is configured with a self-signed certificate by default.

5. On an internet-facing system, you can set up a signed certificate using [Let's Encrypt](https://letsencrypt.org/) or a similar service. Certificate locations can be updated at `/etc/apache2/sites-enabled/indi-allsky.conf` (or equivalent Caddy/Nginx configuration).

