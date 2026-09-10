# Overview
indi-allsky has full support for operating in a Docker containerized environment. Each component is isolated into a dedicated container adhering to container best practices, while sharing a single unified, multi-arch image built from the official APT repository.

If you do not already have a Docker host setup, install Docker Engine and the Docker Compose plugin.

### Platforms
* x86_64 (`amd64`)
  * Linux
* aarch64 (`arm64`)
  * Linux (Raspberry Pi 4/5, single-board computers)

## Docker Setup
Install Docker from the official Docker repositories:
https://docs.docker.com/engine/install/

### Non-privileged User
Set up a non-privileged user on your host to manage Docker containers:

```bash
sudo usermod -a -G docker "$USER"
# Logout and login again for group changes to take effect
```

## indi-allsky Setup

### 1. Clone Code Repository
```bash
git clone https://github.com/aaronwmorris/indi-allsky.git
cd indi-allsky/docker/
```

### 2. Configure Environment
Copy the template configuration to `.env`:
```bash
cp env_template .env
```
Self-signed SSL certificates, cryptographic encryption keys, Nginx reverse proxy routing, and Mosquitto broker configurations are all automatically self-bootstrapped on first container startup without requiring any host configuration scripts.

### 3. Configure Camera Driver
Edit `.env` to select your camera driver:
```ini
INDIALLSKY_INDI_CCD_DRIVER=indi_asi_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_qhy_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_toupcam_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_altaircam_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_ogmacam_ccd_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_omegonprocam_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_playerone_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_svbony_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_libcamera_ccd
```

#### QHY Note
QHY cameras require firmware loading via Cypress WestBridge. Starting the `indiserver` container twice may be required to detect the re-enumerated camera device node.

### 4. Raspberry Pi CSI/MIPI Cameras (libcamera)
If you are using a Raspberry Pi CSI ribbon-cable camera (Camera Module v1/v2/v3, HQ camera):
1. In `.env`, set:
   ```ini
   INDIALLSKY_INDI_CCD_DRIVER=indi_libcamera_ccd
   ```
2. In `docker-compose.yaml`, uncomment `privileged: true` and the `/run/udev` and `/dev` volume mappings under `capture.indi.allsky` to grant direct hardware device access.

### 5. Optional MQTT Broker (Mosquitto)
The `mosquitto.indi.allsky` container is optional. If you do not plan to use MQTT or already have an external broker (such as Home Assistant's Mosquitto add-on):
1. In `docker-compose.yaml`, comment out the `mosquitto.indi.allsky` service and the `mosquitto_data_indi_allsky` volume at the bottom.
2. If connecting to an external broker, specify `INDIALLSKY_MQTT_HOST=<broker_ip_or_host>` in `.env`, or configure MQTT publishing directly in the web UI under **Configuration** &rarr; **MQTT Publishing**.

## Build Containers
The single Dockerfile installs pre-compiled binaries from the official APT repository (`https://apt.indi-allsky.org`):

```bash
docker compose build
```

## Run Containers
```bash
docker compose up -d
```

## Stop Containers
```bash
docker compose down
```

## Architecture & Container Reference

### Containers
* `indiserver.indi.allsky`
  * Runs INDI server with configured camera & GPS drivers (privileged for USB access)
* `capture.indi.allsky`
  * Main capture loop ([allsky.py](file:///home/hamish/git/indi-allsky/allsky.py)) or dark frame generator
* `gunicorn.indi.allsky`
  * Python WSGI application server running Flask web UI and database migrations
* `webserver.indi.allsky`
  * Nginx reverse proxy with TLS termination and direct image file serving
* `mariadb.indi.allsky`
  * MariaDB 11 relational database
* `mosquitto.indi.allsky`
  * Eclipse Mosquitto MQTT broker

### Exposed Ports
* `webserver`: `8080:80`, `8443:443`
* `indiserver`: `17624:7624`
* `mariadb`: `13306:3306` (host-accessible for tools)
* `mosquitto`: `18883:8883`, `18081:8081`

### Volumes
* `config_indi_allsky`: Persistent configuration directory (`/etc/indi-allsky`) and secret encryption keys
* `images_indi_allsky`: Captured allsky image archive
* `migrations_indi_allsky`: Flask database migration history
* `database_indi_allsky`: MariaDB persistent data directory
* `mosquitto_data_indi_allsky`: MQTT persistent storage

## Pre-built Container Images (GHCR)
Pre-built multi-architecture (`linux/amd64`, `linux/arm64`) Docker images are automatically published to GitHub Container Registry (GHCR):

* **Stable Channel**:
  `ghcr.io/aaronwmorris/indi-allsky:stable` (or `:latest`, `:vX.Y.Z`)
  *Automatically built and published on each tagged release after Debian packages are deployed.*
* **Nightly Channel**:
  `ghcr.io/aaronwmorris/indi-allsky:nightly` (or `:nightly-YYYYMMDD`)
  *Automatically built and published on each nightly Debian package build.*

To use pre-built images without building locally:
In `.env`, uncomment:
```ini
INDIALLSKY_IMAGE=ghcr.io/aaronwmorris/indi-allsky:stable
# Or:
#INDIALLSKY_IMAGE=ghcr.io/aaronwmorris/indi-allsky:nightly
```
Then start the stack:
```bash
docker compose pull && docker compose up -d
```

## Updating indi-allsky
* **If using pre-built GHCR images**:
  ```bash
  docker compose pull
  docker compose up -d
  ```
* **If building locally from source**:
  ```bash
  docker compose build --no-cache --pull
  docker compose up -d
  ```

## Running CLI Commands in Container
To execute administration tools inside the running application container:

### User Management
```bash
docker compose exec gunicorn.indi.allsky python3 /usr/share/indi-allsky/misc/usertool.py adduser
docker compose exec gunicorn.indi.allsky python3 /usr/share/indi-allsky/misc/usertool.py setadmin -u <username>
```

### Home Assistant Auto-Discovery
```bash
docker compose exec capture.indi.allsky python3 /usr/share/indi-allsky/misc/home_assistant_auto_discovery.py
```