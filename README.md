# indi-allsky

[![Build & Package Debian Release](https://github.com/aaronwmorris/indi-allsky/actions/workflows/package-deb.yml/badge.svg)](https://github.com/aaronwmorris/indi-allsky/actions/workflows/package-deb.yml)
[![APT Repository](https://img.shields.io/badge/APT%20Repo-apt.indi--allsky.org-blue?logo=debian&logoColor=white)](https://apt.indi-allsky.org/)
[![Latest Release](https://img.shields.io/github/v/release/aaronwmorris/indi-allsky?color=blue&label=Latest%20Release)](https://github.com/aaronwmorris/indi-allsky/releases/latest)
[![Nightly Build](https://img.shields.io/badge/Nightly%20Build-Pre--Release-orange?logo=github&logoColor=white)](https://github.com/aaronwmorris/indi-allsky/releases/tag/nightly)
[![Architectures](https://img.shields.io/badge/Architectures-arm64%20(RPi%204%2F5)%20%7C%20amd64-green?logo=raspberrypi&logoColor=white)](https://github.com/aaronwmorris/indi-allsky/releases)
[![Supported OS](https://img.shields.io/badge/Distributions-Debian%2012%2F13%20%7C%20Ubuntu%2024.04%2F26.04-informational?logo=ubuntu&logoColor=white)](https://github.com/aaronwmorris/indi-allsky/releases)
[![Python Version](https://img.shields.io/badge/python-3.9+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

indi-allsky is software used to manage a Linux-based All Sky Camera using the INDI framework.  Theoretically, any INDI supported CCD/CMOS camera can be functional.

![](./content/20210930_224951.jpg)
*Pictured: SpaceX Cargo Dragon (over Georgia) headed for splashdown off the coast of Florida*

## New Features
* OIDC (OpenID Connect) Authentication (beta)
    * Support for external identity providers (Keycloak, Authentik, Google, GitHub, etc.) for Single Sign-On (SSO).
* Auto-Gain Support
    * Auto-Gain with Exposure Priority automatically tries to scale the exposure to the maximum setting and adjusts gain to maintain consistent image brightness.  Exposure is maximized to ensure you do not miss any events in the sky.
* Real-Time Keogram
    * A keogram is generated in realtime with every image that is taken
* Long Term Keogram
    * Automates the generation of Keograms that could span months or years
* Moon Overlay
    * Realtime accurate representation of illumination of the moon
* Satellite Tracking
* ADS-B Aircraft Tracking
    * Use a SDR to tag aircraft that appear in your camera
* Mini-Timelapses
    * Create videos of specific events captured with your camera
* Weather API
    * OpenWeather Map API
    * Weather Underground API
    * Astrospheric API
    * Ambient Weather API
    * Ecowitt API
* Native Fan controller support
    * Standard
    * PWM Controlled
    * Software PWM
    * Adafruit Motor Shield [MotorKit]
    * DockerPi 4 Channel Relay Hat
    * MQTT controlled remote fan
* Native Dew Heater support
    * Standard
    * PWM Controlled
    * Software PWM
    * Adafruit Motor Shield [MotorKit]
    * DockerPi 4 Channel Relay Hat
    * MQTT controlled remote dew heater
* Native Temperature Sensor support
    * DS18B20 1-wire
    * DHT11/22
    * BMP180
    * BMP280 (i2c & SPI)
    * BME280 (i2c & SPI)
    * BME680 (i2c & SPI)
    * BMP3xx (i2c & SPI)
    * Si7021
    * SHT20
    * SHT3x
    * SHT40/41/45
    * HTU21D
    * HTU31D
    * AHT10/20
    * HDC302x
    * LM35 via ADS1x15 ADC
    * TMP36 via ADS1x15 ADC
    * MLX90614 Sky Temperature
    * MLX90615 Sky Temperature
    * MLX90640 Thermal Camera
    * SCD-30
    * SCD-40/41
* Light (Lux) Sensors
    * TSL2561
    * TSL2591
    * VEML7700
    * BH1750
    * SI1145
    * LTR390
* Magnetometers
    * MMC5983MA 3-axis
* IMU Sensors
    * ICM20X (Magnetometer only)
    * MPU6050 (Temp only)
* VOC/Air Quality Sensors
    * SGP40
* Current Sensors
    * INA219
    * INA228
    * INA260
    * INA23x
    * INA3221
* Lightning Sensors
    * AS3935 (beta)
* Rain Sensors
    * FC37
* Waveshare Environment Sensor HAT
* Waveshare UPS hat (e) battery monitor i2c readings
* Generic GPIO controls
* MQTT Broker sensors
    * Subscribe to topics as sensor input
* Mechanical focuser support
    * 28BYJ-48 Stepper
    * A4988 with NEMA17 Stepper
    * Adafruit Motor Shield [MotorKit]
* Use star metrics (in addition to ADU) for star trails generation
* Generate thumbnails to reduce load time in Timelapse view
* Panorama timelapse generation
* Fish-eye to Panoramic perspective
* Upload timelapse videos directly to YouTube
* Cardinal direction labels
* Satellite tracking and visibility info
* Wildfire smoke reporting *(North America only)*
* Aurora prediction and Kp-index reporting

## Features
* RAW data is the default and preferred input
    * INDI - 16-bit FITS data
    * libcamera - 16-bit DNG data
    * Also supports 8-bit RGB (RGB24), PNG, and JPEG input
* Multiple camera vendor support
    * ZWO
    * Svbony
    * QHY
    * Player One Astronomy
    * ToupTek
    * Altair
    * Omegon Pro
    * OGMA
    * Starlight Xpress
    * Raspberry Pi Camera Modules
        * HQ Camera (IMX477)
        * IMX378
        * Camera Module v3 (IMX708)
        * AI Camera (IMX500)
        * IMX678 Darksee
        * IMX283 Klarity/OneInchEye
        * IMX519
        * IMX335
        * IMX462
        * IMX327
        * 64MP HawkEye (IMX682)
        * 64MP OwlSight (OV64A40)
        * other libcamera supported modules
    * Raspberry Pi Camera modules remotely controlled via MQTT
        * HQ Camera (IMX477)
        * IMX378
        * Camera Module v3 (IMX708)
        * 64MP OwlSight (OV64A40)
        * Additional cameras upon request
    * DSLRs
    * Generic web cameras
    * More to come
* Image stretching (16-bit)
    * Standard Deviation Cutoff (Original)
    * Midtone Transfer Function
* Multi-image stacking
* Dark calibration frames to remove hot pixels
* Camera temperature control (for cameras with active cooling)
* Timelapse video generation
* GPS support
* Images tagged with EXIF data (JPEG only)
* TrueType font support for image labels
* Remote web portal
* Network file transfers - Upload images and videos to remote site
    * S3 Object Storage support
        * Amazon Web Services
        * Google Cloud Storage
        * Oracle OCI Storage
* Publish data to an MQTT service for monitoring
    * Home Assistant Auto-Discovery integration
* Keograms
* Star Trails
* Automatic meteor/plane/satellite detection
* Docker containerization support
* Images display local hour angle of sun and moon
* Moon mode - reduced gain when the moon is overhead
* Remote INDI server operation - operate camera remotely over the network
* Pseudo-Sky Quality Meter - Use your all sky camera to measure sky brightness/quality
* Relational database stores image and timelapse information
    * SQLite (default)
    * MySQL/MariaDB


## Frequently Asked Questions

https://github.com/aaronwmorris/indi-allsky/wiki/FAQ


## Requirements
* A computer running a modern Linux distribution, such as a Raspberry Pi
    * Multicore is recommended
        * ARM
        * x86_64
    * 2GB RAM recommended, 1GB minimum
        * 512MB is adequate for image acquisition, but not enough to generate timelapse videos with ffmpeg
    * 64GB of storage minimum to store 2 months of videos and 30 days of JPEG images.
    * (Optional) Internet connectivity for image uploading
* Camera
    * Most INDI supported astro/planetary cameras will work
    * [libcamera](https://github.com/aaronwmorris/indi-allsky/wiki/libcamera-enablement) - Raspberry Pi camera module


## Distribution support
| Distribution                    | Native Package (`.deb`) | Note |
| ------------------------------- | ----------------------- | ---- |
| **Raspberry Pi OS 13 (trixie)** | **Supported (`.deb`)**  | **RECOMMENDED** (arm64, amd64) |
| **Raspberry Pi OS 12 (bookworm)** | **Supported (`.deb`)**  | **RECOMMENDED** (arm64, amd64) |
| Raspberry Pi OS 11 (bullseye)   | Manual (`setup.sh`)     | Compile INDI with build_indi.sh |
| Raspberry Pi OS 10 (buster)     | (DO NOT USE)            | |
| **Debian 13 (trixie)**          | **Supported (`.deb`)**  | **RECOMMENDED** (arm64, amd64) |
| **Debian 12 (bookworm)**        | **Supported (`.deb`)**  | **RECOMMENDED** (arm64, amd64) |
| Debian 11 (bullseye)            | Manual (`setup.sh`)     | Compile INDI with build_indi.sh |
| Debian 10 (buster)              | (DO NOT USE)            | |
| **Ubuntu 26.04 (resolute)**     | **Supported (`.deb`)**  | **RECOMMENDED** (arm64, amd64) |
| **Ubuntu 24.04 (noble)**        | **Supported (`.deb`)**  | **RECOMMENDED** (arm64, amd64) |
| Ubuntu 22.04 (focal)            | Manual (`setup.sh`)     | INDI installed from ppa:mutlaqja/ppa |
| Linux Mint 22                   | **Supported (`.deb`)**  | Based on Ubuntu 24.04 (Noble) |
| Linux Mint 21                   | Manual (`setup.sh`)     | Based on Ubuntu 22.04 |
| Arch Linux                      | Manual (`setup.sh`)     | Compile INDI with build_indi.sh |
| Armbian                         | **Supported (`.deb`)**  | Use Bookworm/Trixie/Noble/Resolute .deb packages |
| Stellarmate 1.8.x               | Pre-installed           | INDI pre-installed |


## Platform support
| Platform        | Support         | Note |
| --------------- | --------------- | ---- |
| x86_64 (amd64)  | Excellent       | Native `.deb` packages provided |
| aarch64 (arm64) | Excellent       | Native `.deb` packages provided (Raspberry Pi 4 / 5, etc.) |
| armv7l (armhf)  | Not working     | 32-bit platforms lack required scientific Python wheels (`dask-image`, `pyarrow`) |
| armv6l (armhf)  | Not Recommended | Raspberry Pi 1 / Zero v1 |
| x86 (32-bit)    | Problematic     | Lack of pre-compiled wheels |


## INDI support
| Version         | Note |
| --------------- | ---- |
| v2.2.4+         | **Bundled in official `.deb` releases** |
| v2.2.3          | Supported |
| v2.2.2          | Supported |
| v2.2.0          | Supported |
| v2.1.9          | indi_libcamera_ccd is stable |
| v2.0.8          | Minimum for Ubuntu 24.04 |


### Camera SDK Versions
https://github.com/aaronwmorris/indi-allsky/wiki/indilib-3rdparty-SDK-versions


## Single Board Computer support
| Board                         | Note |
| ----------------------------- | ---- |
| Raspberry Pi 5                | Recommend 64-bit trixie (13) or bookworm (12) with native `.deb` |
| Raspberry Pi 4                | Recommend 64-bit trixie (13) or bookworm (12) with native `.deb` |
| Raspberry Pi 3                | Recommend 64-bit trixie (13) or bookworm (12), recommend 1GB of swap |
| Raspberry Pi Zero 2           | Recommend 64-bit trixie (13) or bookworm (12), memory constrained |
| Raspberry Pi Zero             | Recommend 32-bit bullseye (11), memory constrained |
| Raspberry Pi Zero W           | Recommend 32-bit bullseye (11), memory constrained, WiFi gets disabled so build from console |
| Rock Pi                       | Supported with 64-bit Debian/Ubuntu `.deb` |
| Libre Computer (Le Potato)    | Supported with 64-bit Debian/Ubuntu `.deb` |
| Orange Pi                     | Supported with 64-bit Debian/Ubuntu `.deb` |
| Orange Pi PC Plus             | Requires 2GB swap (and patience) to build all python modules |
| Banana Pi                     | Supported with 64-bit Debian/Ubuntu `.deb` |
| BeagleBone                    | Supported with 64-bit Debian/Ubuntu `.deb` |


## Memory Requirements for Timelapses
Memory requirements are primarily driven by the resolution of the timelapse generated by the FFMPEG utility. A higher resolution camera can be used on lower memory systems by scaling the output resolution of the FFMPEG process.

| Output Resolution  | Recommended Memory | Minimum Memory        | FFMPEG Process Memory |
| ------------------ | ------------------ | --------------------- | --------------------- |
| 852 x 480 (0.4MP)  | 1GB                | <1GB with swap        | 0.2GB                 |
| 1280 x 960 (1.2MP) | 2GB                | 1GB with 1GB swap     | 0.4GB                 |
| 1920 x 1080 (2MP)  | 2GB                | 1GB with 1GB swap     | 0.6GB                 |
| 3840 x 2160 (8MP)  | 4GB                | 2GB with 1GB swap     | 1.7GB                 |
| 3008 x 3008 (9MP)  | 4GB                | 2GB with 1GB swap     | 1.8GB                 |
| 4056 x 3040 (12MP) | 4GB                |                       | 2.5GB                 |
| 6224 x 4168 (26MP) | 8GB                |                       | 5.0GB                 |
| 9152 x 6944 (64MP) | 16GB               |                       | 12.0GB                |

# Installation

### Option 1: Official APT Repository (Recommended)
Install and automatically receive updates on Raspberry Pi OS, Debian, and Ubuntu via `apt`:

```bash
# 1. Add GPG Keyring
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.indi-allsky.org/key.gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/indi-allsky.gpg
sudo chmod a+r /etc/apt/keyrings/indi-allsky.gpg

# 2. Add APT Repository (Stable Channel)
sudo tee /etc/apt/sources.list.d/indi-allsky.sources <<EOF
Types: deb
URIs: https://apt.indi-allsky.org
Suites: $(lsb_release -cs)
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/indi-allsky.gpg
EOF

# 3. Install indi-allsky
sudo apt update
sudo apt install -y indi-allsky
```

*(An interactive terminal wizard will prompt for camera driver selection, admin credentials, and observatory coordinates).*

Visit the [APT Repository Web Portal](https://apt.indi-allsky.org/) to view repository status or switch to the **Nightly** release channel.

---

### Option 2: Direct `.deb` Package Download
Pre-compiled `.deb` packages bundle all 100+ dependencies, pre-compiled wheels, and camera drivers for a 10-second installation without compilation.

1. **Download Packages**:
   Download the `.deb` release matching your distribution (Bookworm, Noble, Resolute, or Trixie) and architecture (`arm64` or `amd64`) from the [GitHub Releases](https://github.com/aaronwmorris/indi-allsky/releases).
2. **Install**:
   ```bash
   sudo apt update
   sudo apt install -y ./*.deb
   ```
3. **Interactive Configuration**:
   Follow the interactive setup wizard to select your camera driver, admin credentials, and observatory coordinates.
4. **Access Web Dashboard**:
   Open `https://<device-ip>/indi-allsky/` in your browser.

---

### Option 3: Docker Containerization
indi-allsky has full support for running in a unified containerized environment. Check out the `docker/` folder for Docker assets and documentation:

https://github.com/aaronwmorris/indi-allsky/wiki/Docker

---

### Option 4: Manual Source Installation (`setup.sh`)
For rolling development or unsupported distributions, the traditional installation script remains available:

https://github.com/aaronwmorris/indi-allsky/wiki/Getting-Started


### Logs
* Main daemon logs: `/var/log/indi-allsky/indi-allsky.log` (syslog facility local6, rotated daily)
* Web interface logs: `/var/log/indi-allsky/webapp-indi-allsky.log` (syslog facility local7)
* Systemd service status:
  ```bash
  sudo systemctl status indi-allsky.service gunicorn-indi-allsky.socket indiserver.service apache2
  ```


## Updating

### Updating `.deb` Package Installations
```bash
sudo apt update
sudo apt install -y ./indi-allsky_*.deb
```
Package upgrades automatically backup and preserve existing configurations (`/etc/indi-allsky/flask.json`), retain database data, and run schema migrations seamlessly.

### Updating Source / `setup.sh` Installations
Pull updates from GitHub and re-run `setup.sh`:
https://github.com/aaronwmorris/indi-allsky/wiki/Updating-indi-allsky


### Security
In an effort to increase security, I am trying to do a better job of tracking security issues in indi-allsky and the associated Software Bill of Materials.  GitHub Dependabot alerts are enabled which help track things like vulnerable Python modules.

https://github.com/aaronwmorris/indi-allsky/wiki/Security-considerations

https://github.com/aaronwmorris/indi-allsky/wiki/Security-Notifications


### libcamera support
libcamera is a new camera interface designed to replace the legacy camera interfaces such as V4L2.

Proper libcamera support is only working on Raspberry Pi OS 11 (bullseye) on Raspberry Pi 3 & 4.

https://github.com/aaronwmorris/indi-allsky/wiki/libcamera-enablement

*Note: Genererating and processing raw (dng) files on a system with less than 1GB of memory and libcamera will cause out-of-memory conditions.  There is an option to generate JPEG or PNG files with libcamera which solves this issue.*


### Dark frames
indi-allsky fully automates the capture and processing of master dark calibration frames. Currently, sigma clipping and average methods are supported.

https://github.com/aaronwmorris/indi-allsky/wiki/Dark-Calibration-Frames


### Moon mode

This is a special night time operating mode intended to reduce gain when the moon is more illuminated and above the horizon


## Keograms
Keograms are a visual representation of the entire timelapse video in a single frame.  Every image is rotated so that the vertical aligns to the meridian and then the center-vertical column is extraced from each frame and compiled into the keogram.  The rotation parameter in the config is KEOGRAM_ANGLE

https://github.com/aaronwmorris/indi-allsky/wiki/Keogram-Rotation

Below you can see perodic clouds passed over between 8-9pm and again between 4-5am.  If you look closely enough, you can see the Pleiades star cluster and the Orion constellation as it passed through the meridian in this example keogram.

![](./content/keogram_example.jpg)

*Note: The horizontal lines are just hot pixels that were subtracted by the dark frame.*


## Star Trails
Star trail images stack the stars from each frame to show their progression across the sky.

![](./content/startrails_example.jpg)


### Star Trails Timelapse
Video of the star trails being stacked in real-time!

[YouTube](https://youtu.be/pLJbTzlyBkM)


## Smoke reporting
indi-allsky polls data from [NOAA Office of Satellite And Product Operations](https://www.ospo.noaa.gov/) to report the level of smoke coverage in your location.  The OSPO provides KML map data for their [Hazard Mapping System Fire and Smoke Product](https://www.ospo.noaa.gov/Products/land/hms.html) [HMS].  indi-allsky processes the smoke polygons in the KML map data and checks if your location (~35 mile radius) is contained within the smoke areas.

Smoke data is updated every 3 hours from NOAA.  Smoke data is also published with the MQTT data.

*Note: Data is only available for **North America**.*


## Aurora, Kp-index, and Solar Wind
indi-allsky utilizes data from [NOAA Space Weather Prediction Center](https://www.swpc.noaa.gov/) to predict the possibility of Aurora in your location.  The SWPC provides data using the Ovation Aurora Model for aurora predictions.  indi-allsky uses the Ovation data to create an aggregate score within a ~500 mile radius around your location.

The current Kp-index value is also polled from NOAA.  This is the measurement of the disturbance of the Earth's magnetic field, ranging from 0-9.  Values higher than 5 are good indicators of stronger solor storm activity which creates aurora.

The Kp-index data, combined with the Ovation data, gives an objective prediction of the visibility of Aurora for your location.

Also available are Magnetic field Bt, Bz, Hemispheric power, and Solar Wind speed and density data.

Aurora data is updated every 60 minutes from NOAA.  Aurora data is also published with the MQTT data.


## Satellite Tracking
Satellite tracking data is used to track the visibility of specific satellites like the International Space Station and Hubble Space Telesope.  Rise, transit, and set times are available in the Astropanel view.

Orbital data is downloaded in TLE format from [CelesTrak](https://celestrak.org/NORAD/elements/)


## Star Detection
indi-allsky utilizes OpenCV pattern matching to detect and count the number of stars in the view.  Star counts are a good objective measurement of sky conditions.

Star and meteor detection support using detection masks to customize your Region of Interest if there are obstructions in your view.
https://github.com/aaronwmorris/indi-allsky/wiki/Detection-Masks


## Meteor Detection
Using OpenCV Canny edge detection and Hough Line Transform, indi-allsky is able to perform basic line detection to detect meteor and fireball trails in the view.  Airplane and satellite trails are also detected using this method.  Images are tagged with an asterisk in the image viewer if a trail has been detected.


## Focus Mode
Focus mode is a special setting that generates images more often and implements a Variance of Laplacian scoring algorithm on the image to assist with focusing the camera.  Images are not saved when focus mode is enabled.


## Stacking
indi-allsky supports image stacking to increase details and contrast in the image.

The following stacking modes are provided:
* Maximum - The maximum value of each pixel in the stack is used.  Increases contrast of stars and sky overall.  Extends the effect of satellite/airplane trails, meteors, and other phenomena.
* Average - The average value of each pixel is used in the resulting image.
* Minimum - The minimum value of each pixel is used.  This has the effect of removing airplane and satellite trails (and meteors).

The `Stack split screen` option will split the image into two panes.  The left pane will show the original image data and the right pane will contain the stacked data.

Regarding performance, stacking does have an impact to memory and CPU utilization.  indi-allsky stores the RAW images used for the stack in memory.  A single 1920x1080 (1K) image is approximately 8MB.  Four 1K images will require 32MB of memory.  A single 4056x3040 (4K) RAW image is ~25MB, four would require 100MB of memory (at all times).

CPU utilization and memory is reasonable for stacking 1K images on Raspberry Pi 3 (1GB) hardware, but 4K stacking starts to significantly impact response times.  Strongly recommend Raspberry Pi 4 with 2+GB of memory for 4K images.

Registration (alignment) requires significantly more CPU time and doubles the memory requirement since the registered images must also be stored in memory.  Registering one 1920x1080 (1K) image (reference + image) requires 2-3 seconds on Raspberry Pi 3 hardware.


## Web Interface

The indi-allsky web interface is built on the Flask MVC framework.  It is designed to be a dashboard for your sky.  Included is the ability to fully manage the camera configuration without having to manually edit from the command line.

Most views do not require authentication.  Credentials for accessing the privileged areas are defined upon the first setup of the software.


### Home Page
![](./content/webui_home.png)


### Charts
Early evening, the sun was still going down, but a cloud passed by, increasing the average brightness and lowering the star count.
![](./content/webui_chart01.png)

A large cloud passed over significantly increasing the brightness of the sky and blocking out almost all of the stars.
![](./content/webui_chart02.png)


### Image viewer
Historical images browsing.
![](./content/webui_images.png)
*Pictured: A small satellite flare.*


### Timelapse viewer
Historical Star trails and Keograms.  The Keogram image is linked directly to the timelapse video for the night.
![](./content/webui_timelapse_mono.png)


### System Info
![](./content/webui_systeminfo.png)


## Database

All media generated are logged in a local SQLite database stored in /var/lib/indi-allsky/indi-allsky.sqlite  This database is used as the source of images for timelapse and keogram generation, as well as, for displaying images via the web interfaces.

The database is managed via the python modules SQLAlchemy and alembic to provide migrations (schema upgrades) automatically in the setup.sh script.


## Remote Web Portal - SyncAPI

An on-premises indi-allsky system can synchronize images and timelapses to a cloud-based indi-allsky web server instance using the built in SyncAPI.  Remote users can browse the remote indi-allsky web instance without touching the system running the camera.  Images are synced in real-time.

In effect, the indi-allsky web interface is its own remote web portal.

A remote indi-allsky instance can support multiple clients using SyncAPI with a single instance.  Users can easily switch between the cameras in the web interface.  The SyncAPI can also be combined with the S3 Object Storage functionality to offload image storage to a cloud service.


### OIDC Authentication

The OIDC (OpenID Connect) feature allows you to offload user authentication to an external identity provider (IdP) such as Keycloak, Authentik, Google, or GitHub. This provides a Single Sign-On (SSO) experience and allows for centralized management of users and permissions.


### Home Hosting

The indi-allsky web interface is designed to be directly exposed to the Internet, if you have sufficient bandwidth on your home Internet connection.  A simple, yet effective, access control system is implemented to let anonymous (or authenticated) users safely browse images and videos without exposing privileged controls.  Only users with assigned administrative authority can make changes.

https://github.com/aaronwmorris/indi-allsky/wiki/Security-considerations

It is also possible to use cloud security offerings like [Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/) to further protect your indi-allsky site.


## Sensor support

indi-allsky supports reading sensors natively on single board computers like Raspberry Pi.

https://github.com/aaronwmorris/indi-allsky/wiki/Sensors


## Dew Heater support

Native dew heater support is built in for standard and PWM controlled dew heaters.

https://github.com/aaronwmorris/indi-allsky/wiki/Dew-Heater-Support


## Fan Controller support

Native fan controller support is built in for standard and PWM controlled fans.

https://github.com/aaronwmorris/indi-allsky/wiki/Fan-Control


## Focuser support

If you built your system with a focuser, it is now possible to control the focuser within the Focus view.  `28BYJ-48` and `NEMA17` steppers are currently supported.

https://github.com/aaronwmorris/indi-allsky/wiki/Focuser-Device


## YouTube support
indi-allsky supports being able to upload timlapse and star trail videos directly to YouTube

https://github.com/aaronwmorris/indi-allsky/wiki/Youtube-Uploads


## S3 Object Storage

You may choose to upload images and timelapse files to an S3 bucket.  Once the images are in the bucket, images and videos in the web interface will be loaded directly from S3 instead of the local indi-allsky web server.  You could easy host the web interface from your home internet connection and just have the large media files served from S3.

Currently, only Amazon Web Services is supported, but other providers could be easily be added.  Just open an issue.

Estimated cost for an allsky camera holding 90 days of timelapses and 30 days of images on AWS (day and night):  ~$2.00 (USD) per month  (50GB of data + 180,000 requests)

AWS S3 and GCP Storage are currently supported.

*Note:  As of writing this, the AWS free tier for S3 supports 5GB and 2000 requests per month.  In a single night, I achieved 80% of the requests limit (8 hours of images every 15 seconds is 1920 upload requests).  The free tier is only sufficient for basic testing, but not long term usage.*


## GPS

GPS support is provided through [indi_gpsd](https://www.indilib.org/aux/gps.html) and GPSd integration.  Any GPS hardware supported by GPSd will work.

JPEG and FITS Images exported [optional] by indi-allsky will be properly tagged with Geographic (latitude/longitude) and Astrometric (RA/dec) information in the headers.  Tags include geographic location regardless of GPS support, but the information will be much more precise with the GPS module.


## Performance

indi-allsky itself is written in python, but python is just the glue between the different libraries, most of which are C based which makes indi-allsky extremely fast.  A 1920 x 1080 image can be dark frame calibrated, debayered, histogram processed, text applied, and compressed to a JPG in less than 0.5 seconds on Raspberry Pi 3 class hardware.  PNG processing is a little more taxing, but usually only takes a few seconds.

ffmpeg video processing is considerably more expensive.  A 2 minute 1920x1080 h.264 encoded video compiled from 3,000 frames requires ~20 minutes on Raspberry Pi 3 (4 core) hardware.  Encoding takes place in a separate process from image aqcuisition and image processing and is run at the lowest CPU priority so image acquision is not impacted.


## Software Dependencies

| Function          | Software      | URL |
| ----------------- | ------------- | --- |
| Camera interface  | INDI          | https://indilib.org/ |
|                   | pyindi-client | https://github.com/indilib/pyindi-client |
|                   | libcamera     | https://libcamera.org/ |
| Image processing  | OpenCV        | https://opencv.org/ |
|                   | opencv-python | https://github.com/opencv/opencv-python |
|                   | Pillow        | https://pillow.readthedocs.io/ |
|                   | piexif        | https://piexif.readthedocs.io/ |
|                   | astropy       | https://www.astropy.org/ |
|                   | astroalign    | https://astroalign.quatrope.org/ |
|                   | ccdproc       | https://ccdproc.readthedocs.io/ |
|                   | numpy         | https://numpy.org/ |
| Video processing  | ffmpeg        | https://www.ffmpeg.org/ |
| Astrometry        | pyephem       | https://rhodesmill.org/pyephem/ |
| File transfer     | pycurl        | http://pycurl.io/ |
|                   | paramiko      | http://www.paramiko.org/ |
|                   | paho-mqtt     | https://www.eclipse.org/paho/ |
|                   | requests      | https://requests.readthedocs.io/en/latest/ |
| S3 Object Storage | boto3         | https://boto3.amazonaws.com/v1/documentation/api/latest/index.html |
|                   | apache-libcloud | https://libcloud.apache.org/ |
|                   | google-cloud-storage | https://cloud.google.com/python/docs/reference/storage/latest |
| Database          | SQLite        | https://www.sqlite.org/ |
|                   | SQLAlchemy    | https://www.sqlalchemy.org/ |
|                   | alembic       | https://alembic.sqlalchemy.org/ |
|                   | mysql-connector-python | https://dev.mysql.com/doc/connector-python/en/ |
|                   | PyMySQL       | https://pymysql.readthedocs.io/en/latest/ |
| GPS               | GPSd          | https://gpsd.gitlab.io/gpsd/ |
| Web interface     | Flask         | https://flask.palletsprojects.com/ |
|                   | WTForms       | https://wtforms.readthedocs.io/ |
|                   | flask-login   | https://flask-login.readthedocs.io/ |
|                   | Authlib       | https://authlib.org/ |
|                   | Gunicorn      | https://gunicorn.org/ |
|                   | Apache        | https://httpd.apache.org/ |
|                   | NGINX         | https://www.nginx.com/ |
| Hardware Sensors  | Circuit Python | https://circuitpython.org/ [GitHub](https://github.com/adafruit) |


## Architecture

indi-allsky utilizes python's multiprocessing library to enable parallelizing tasks so that image processing does not interfere with image aquisition, etc.

![](./content/indi-allsky-arch.svg)


## Configuration

All configuration is read from the database.  Almost all of the configuration is managed via the web interface.
You may use the config.py utility to manipulate the configuration from the command line.


## Tested Hardware

3-4 weeks of constant runtime with no intervention are common.  The only reason I restart my cameras are code updates (or power failures).

The hardware below has at least been plugged in and tested for correct detection and CFA decoding.

| Vendor   | Model               | Rating | Notes |
| -------- | ------------------- | ------ | ----- |
| ZWO      | ASI120MC-S          | B      | https://github.com/aaronwmorris/indi-allsky/wiki/ASI120MC-S-Camera-Issues |
| ZWO      | ASI678MC            | A      |       |
| ZWO      | ASI676MC            | A      | This camera was designed for all sky systems |
| ZWO      | ASI585MC            | A      |       |
| ZWO      | ASI178MC/MM         | A      |       |
| ZWO      | ASI290MC/MM         | A      |       |
| ZWO      | ASI385MC            | A      |       |
| ZWO      | ASI174MM            | A      |       |
| ZWO      | ASI533MC/MM         | A      |       |
| ZWO      | ASI183MC/MM         | A      |       |
| QHY      | QHY5III485C         | A      | Needs newer [fxload](https://github.com/aaronwmorris/indi-allsky/wiki/Build-fxload-for-USB3-support) utility for firmware |
| QHY      | QHY5LII-M           | A      |       |
| Svbony   | SV305               | B      | ~20% of frames require double the configured exposure time to complete. Likely a firmware bug. |
| Altair   | Hypercam 178C       | A      | Needs [config](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config#altair-hypercam-178c) for full resolution |
| Altair   | GPCAM3 290C         | A      | Needs [config](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config#altair-290c-resolution) for full resolution |
| Altair   | GPCAM3 224C         | A      | Needs [config](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config#altair-224c-resolution) for full resolution |
| Altair   | GPCAM2 290M         | A      |       |
| Touptek  | G3CMOS06300KPA (IMX178) | A  |       |
| Touptek  | G-1200-KMB          | A      |       |
| Player One        | Mars-C                        | A | |
| Player One        | Neptune-C                     | A | |
| Starlight Xpress  | Superstar                     | A | Fixed gain.  Using stretching and/or contrast enhance |
| Datyson           | T7C                           | A | Using indi_asi_ccd driver<br>Recommend ASI120MC Linux compatibility firmware |
| Raspberry Pi      | HQ Camera imx477 (libcamera)  | A | |
| Raspberry Pi      | CM3 imx708 (libcamera)        | A | Minimum 1GB of memory is needed to process RAW images with dark calibration frames |
| Raspberry Pi      | HQ Camera (indi_pylibcamera)  | A | https://github.com/scriptorron/indi_pylibcamera |
| Waveshare         | imx378 (libcamera)            | A | |
| ArduCam           | imx462 (libcamera)            | A | |
| ArduCam           | 64MP HawkEye                  | A | Recommend at least 4GB of RAM for full resolution 9152x6944.  [Options](https://github.com/aaronwmorris/indi-allsky/wiki/libcamera-enablement) available to reduce image size. |
| Canon    | 550D (Rebel T2i)    | A      | Camera resolution and pixel size have to be manually defined in config |
| Canon    | 1300D (Rebel T6)    | A      | Camera resolution and pixel size have to be manually defined in config |
| IP Cameras | indi_webcam_ccd   | C      | Needs [config](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config) for operation |
| Webcams  | indi_v4l2_ccd       | B      | |
| Webcams  | indi_webcam_ccd     | D      | No gain controls.  Little control over image quality. |
| indi     | indi_simulator_ccd  |        | CCD Simulator.  Install GSC to generate sample images. |

If you have an INDI supported camera from a vendor not listed, open an enhancement request and I can work with you to support the camera.


## Gotchas
Common problems you might run into.

* The indi-allsky python processes consume ~500MB of RAM.
    * 1K (1920x1080) h.264 encoding with ffmpeg requires an additional ~500MB of RAM.  1GB of RAM should be the bare minimum system memory.  You should also have 100-500MB of additional swap space to prevent running out of memory during encoding.  2GB of RAM recommended.
    * 4K (3840x2160) h.264 encoding requires an additional 2+GB of RAM.  4GB of RAM recommended.
    * 8K resolution (ArduCam 64MP HawkEye) requires 8GB of RAM for full resolution video processing.
* In Raspberry Pi OS 10, the h.264 codec in ffmpeg has a maximum frame size of 4096×2304 (AVC level 5.1).  If your camera generates higher resolution images, you will need to scale the video  or use the Region of Interest (RoI) options to reduce the frame size.
    * NEW: indi-allsky now has the ability to scale the native resolution images during the ffmpeg encoding phase, so you do not need to pre-scale your images.
    * The RaspberryPi HQ camera has a bin1 image size of 4056x3040.  Setting IMAGE_SCALE to 75 in the config results in a image size of 3042x2280.  Alternatively, you can center crop the image using IMAGE_CROP_ROI set to [0, 368, 4056, 2672] for an image size of 4056×2304.
* ffmpeg in Raspberry Pi OS 11 enables AVC level 6.0+ which permits h.264 resolutions up to 8192×4320 (you must have sufficient system memory)
    * https://en.wikipedia.org/wiki/Advanced_Video_Coding


## File Transfer

indi-allsky supports several file transfer methods.

https://github.com/aaronwmorris/indi-allsky/wiki/File-transfers

| Protocol       | Port |
| -------------- | ---- |
| ftp            | 21   |
| ftpes          | 21   |
| ftps           | 990  |
| sftp           | 22   |
| webdav (https) | 443  |


## MQTT Publishing

indi-allsky supports publishing all sky data to an MQTT service for monitoring.

For more info, see the wiki page: https://github.com/aaronwmorris/indi-allsky/wiki/MQTT-Broker-Publishing


## Blogs, Articles, and Links

Please let me know if you want to make an addition or correction.

* [indilib.org](https://www.indilib.org/research/projects/197-indi-allsky-record-the-sky.html)
* [indilib.org forum thread](https://indilib.org/forum/general/10619-new-all-sky-camera-management-software-indi-allsky.html)
* [CloudyNights.com forum thread](https://www.cloudynights.com/topic/785514-new-all-sky-camera-management-software-indi-allsky/)
* [Gord Tulloch](https://www.openastronomy.ca/2023/01/06/indi-allsky-software-review/)
* [Giles Coochey](https://coochey.net/?cat=29)
* [PampaSkies](http://www.pampaskies.com/gallery3/Equipment/All-Sky-Camera-with-Sky-Condition-Detection)
* [The Suffolk Sky](http://www.suffolksky.com/all-sky-camera/)
* [Boletim da Sociedade Astronômica Brasileira](https://sab-astro.org.br/wp-content/uploads/2023/04/GabrielSantos2.pdf)
* [Aircraft data / ADS-B tracking via adsb.fi](https://allsky-rodgau.com/aircraft-data-ads-b-tracking-for-my-allsky-camera-via-adsb-fi-1336/)
* [indi Allsky live images in WordPress](https://allsky-rodgau.com/indi-allsky-live-images-in-wordpress-structure-and-functionality-of-my-plugin-1648/)
* [Raspberry Pi as a digital picture frame in kiosk mode](https://allsky-rodgau.com/raspberry-pi-as-a-digital-picture-frame-in-kiosk-mode-hardware-setup-troubleshooting-1610/)
* [Automatic indi-allsky backup on external drive](https://allsky-rodgau.com/automatic-indi-allsky-backup-on-external-drive-fritzbox-nas-1653/)
* [Optimal configuration for indi-allsky](https://allsky-rodgau.com/optimal-configuration-for-indi-allsky-stable-day-night-transition-and-reliable-moon-mode-1541/)


## Frontend Development

When modifying frontend templates, CSS, or JS assets, keep the following development setup in mind:

### Environment Setup & Git Hooks
Run `npm install` once in the repository root to install dependencies and configure Git hooks:
```bash
npm install
```
This automatically configures the Git pre-commit hook (`githooks/pre-commit`), which runs `npm run build` and stages updated assets before every commit.

### Building & Testing Assets
When testing template or CSS changes locally, compile the assets manually:
```bash
npm run build
```


## Alternatives

* Thomas Jacquin's Allsky
    * Free, Open source
    * Linux, Single board computer
    * https://github.com/thomasjacquin/allsky
* AllSkEye
    * Free version, Commercial option
    * Windows
    * https://allskeye.com/
* frankAllSkyCam
    * Free, Open source
    * Linux, Single board computer
    * https://github.com/sferlix/frankAllSkyCam
* RPi Meteor Station
    * Free, Open source
    * Linux, Single board computer
    * https://github.com/CroatianMeteorNetwork/RMS
* Meteotux Pi
    * Free version, Commercial option
    * Linux, Single board computer
    * https://www.meteotuxpi.com/
* UFOCapture
    * Shareware, Commercial option
    * Windows
    * https://sonotaco.com/soft/e_index.html


## Commercial hardware

* Deep Sky Dad
    * https://shop.deepskydad.com/
* Titan Astro
    * https://titanastro.com/store/
* Allsky Optics
    * https://www.allskyoptics.com/store
* Oculus All-Sky Cameras
    * https://www.sxccd.com/cameras/oculus-all-sky-cameras/
* Alcor System
    * https://www.alcor-system.com/new/AllSky/Alphea_camera.html

## Star History

<a href="https://star-history.dera.page/#aaronwmorris/indi-allsky&type=date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=aaronwmorris/indi-allsky&type=date&theme=dark&legend=bottom-right" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=aaronwmorris/indi-allsky&type=date&legend=bottom-right" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=aaronwmorris/indi-allsky&type=date&legend=bottom-right" />
 </picture>
</a>

## Acknowledgements

* [Thomas Jacquin](https://github.com/thomasjacquin) - indi-allsky is heavily inspired by his [allsky](https://github.com/thomasjacquin/allsky) software.
* [Marco Gulino](https://github.com/GuLinux) - His examples from [indi-lite-tools](https://github.com/GuLinux/indi-lite-tools) were key to understanding how to work with pyindi-client
* [PixInsight](https://www.pixinsight.com/) - Various algorithms were used that are in the PixInsight documentation
* [Radek Kaczorek](https://github.com/rkaczorek) - [astropanel](https://github.com/rkaczorek/astropanel/) has been integrated into indi-allsky
* [CelesTrak](https://celestrak.org/) - Satellite orbital data
* [Russell Valentine](https://github.com/bluthen) - [fish2pano](https://github.com/bluthen/fish2pano) Fish-eye to panoramic perspective conversion
* [Adafruit Industries](https://www.adafruit.com/) - [Adafruit Github](https://github.com/adafruit) Circuit Python modules enabled indi-allsky to quickly facilitate using many electronics sensors

## Donate
[![](https://www.paypalobjects.com/en_US/i/btn/btn_donate_LG.gif)](https://paypal.me/aaronwmorris)

If you would like to fund equipment purchases for testing (or more Dr Pepper), you can use this link.

**However, I would rather you to donate something to charity.  As a suggestion, the [Ronald McDonald House](https://rmhc.org/) has helped my family in the past.  I would love to hear if you give, please let me know!**
