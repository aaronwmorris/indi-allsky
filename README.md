# Indi Allsky
indi-allsky is software used to manage a Linux-based All Sky Camera using the INDI framework.  Theoretically, any INDI supported CCD/CMOS camera can be functional.

![](./content/20210930_224951.jpg)
*Pictured: SpaceX Cargo Dragon (over Georgia) headed for splashdown off the coast of Florida*

## Features
* Multiple camera vendor support
    * ZWO
    * Svbony
    * QHY
    * Altair
    * ToupTek
    * Starlight Xpress
    * Player One Astronomy
    * Raspberry Pi HQ Camera
    * libcamera support (imx477, imx378, etc)
    * Canon DSLRs
    * Generic web cameras
    * More to come
* Dark frames to remove hot pixels
* Camera temperature control (for cameras with active cooling)
* Multi-image stacking
* Timelapse video generation
* GPS support
* Remote web portal
* Network file transfers - Upload images and videos to remote site
    * S3 Object Storage support
* Publish data to an MQTT service for monitoring
* Keograms
* Star Trails
* Automatic meteor/plane/satellite detection
* Images display local hour angle of sun and moon
* Moon mode - reduced gain when the moon is overhead
* Remote INDI server operation - operate camera remotely over the network
* Pseudo-Sky Quality Meter - Use your all sky camera to measure sky brightness/quality
* Relational database stores image and timelapse information
    * SQLite (default)
    * MySQL/MariaDB

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
    * libcamera/Raspberry Pi camera module

### Distibution support
| Distribution          | Arch           | Note |
| --------------------- | -------------- | ---- |
| Raspbian 11 64-bit    | arm64          | Indi installed from Astroberry apt repo<br />Use libcamera for Raspberry PI HQ camera |
| Raspbian 11 32-bit    | armhf          | Compile indi with build_indi.sh<br />The rawpy module is not availble on 32-bit Arm, therefore DNG/raw libcamera image processing is not available (jpeg/png still possible) |
| Raspbian 10 (Legacy)  | armhf          | Indi installed from Astroberry apt repo |
| Armbian 22.02         | arm64/armhf    | Compile indi with build_indi.sh<br />https://github.com/aaronwmorris/indi-allsky/wiki/Armbian-Tuning |
| Debian 11             | x86_64         | Compile indi with build_indi.sh |
| Debian 10             | x86_64         | Compile indi with build_indi.sh |
| Ubuntu 22.04          | arm64          | Compile indi with build_indi.sh |
| Ubuntu 20.04          | x86_64         | Indi installed from ppa:mutlaqja/ppa |
| Ubuntu 20.04<br />inc. Ubuntu Mate | arm64 | Compile indi with build_indi.sh |
| Ubuntu 18.04          | x86_64         | Indi installed from ppa:mutlaqja/ppa |
| Astroberry Server 2.0 | armhf          | |

MacOS support is theoretically possible, but not tested.

### libcamera support
libcamera is a new camera interface designed to replace the legacy camera interfaces such as V4L2.

Proper libcamera support is only working on Raspbian 11 64-bit on Raspberry Pi 3 & 4.

Note: Genererating and processing raw (dng) files on a system with less than 1GB of memory and libcamera will cause out-of-memory conditions.  There is an option to generate JPEG or PNG files with libcamera which solves this issue.


## Installation
1. Install git
```
apt-get install git
```
2. Clone the indi-allsky git repository
```
git clone https://github.com/aaronwmorris/indi-allsky.git
```
3. Navigate to the indi-allky sub-directory
```
cd indi-allsky/
```
4. Run setup.sh to install the relevant software
```
./setup.sh
```
 * Note:  You may be prompted for a password for sudo
5. Start the software
```
systemctl --user start indiserver
systemctl --user start indi-allsky
```
6. Login to the indi-allsky web application
https://raspberrypi.local/
 * Note: The web server is configured with a self-signed certificate.

### Manual operation
1. Stop indi-allsky service
```
systemctl --user stop indi-allsky
```
2. Activate the indi-allsky python virtual environment
```
source virtualenv/indi-allsky/bin/activate
```
3. Start indi-allsky
```
./allsky.py run
```

## Updating
https://github.com/aaronwmorris/indi-allsky/wiki/Updating-indi-allsky

### Logs
* When indi-allsky is run from the command line, logs are sent to STDERR by default.
* When the indi-allsky service is started, logs are sent to syslog via facility local6.  Logs are stored in /var/log/indi-allsky/indi-allsky.log and rotated daily.


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

Note: The horizontal lines are just hot pixels that were subtracted by the dark frame.


## Star Trails
Star trail images stack the stars from each frame to show their progression across the sky.

![](./content/startrails_example.jpg)

### Star Trails Timelapse
Video of the star trails being stacked in real-time!

[YouTube](https://youtu.be/pLJbTzlyBkM)


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


### Home Hosting

The indi-allsky web interface is designed to be directly exposed to the Internet, if you have sufficient bandwidth on your home Internet connection.  A simple, yet effective, access control system is implemented to let anonymous (or authenticated) users safely browse images and videos without exposing privileged controls.  Only users with assigned administrative authority can make changes.

https://github.com/aaronwmorris/indi-allsky/wiki/Security-considerations

It is also possible to use cloud security offerings like [Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/) to further protect your indi-allsky site.


## S3 Object Storage

You may choose to upload images and timelapse files to an S3 bucket.  Once the images are in the bucket, images and videos in the web interface will be loaded directly from S3 instead of the local indi-allsky web server.  You could easy host the web interface from your home internet connection and just have the large media files served from S3.

Currently, only Amazon Web Services is supported, but other providers could be easily be added.  Just open an issue.

Estimated cost for an allsky camera holding 90 days of timelapses and 30 days of images (day and night):  ~$2.00 (USD) per month  (50GB of data + 180,000 requests)

Note:  As of writing this, the AWS free tier for S3 supports 5GB and 2000 requests per month.  In a single night, I achieved 80% of the requests limit (8 hours of images every 15 seconds is 1920 upload requests).  The free tier is only sufficient for basic testing, but not long term usage.


## GPS

GPS support is provided through [indi_gpsd](https://www.indilib.org/aux/gps.html) and GPSd integration.  Any GPS hardware supported by GPSd will work.

FITs Images exported [optional] by indi-allsky will be properly tagged with Geographic (latitude/longitude) and Astrometric (RA/dec) information in the headers.

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
| Database          | SQLite        | https://www.sqlite.org/ |
|                   | SQLAlchemy    | https://www.sqlalchemy.org/ |
|                   | alembic       | https://alembic.sqlalchemy.org/ |
|                   | mysql-connector-python | https://dev.mysql.com/doc/connector-python/en/ |
|                   | PyMySQL       | https://pymysql.readthedocs.io/en/latest/ |
| GPS               | GPSd          | https://gpsd.gitlab.io/gpsd/ |
| Web interface     | Flask         | https://flask.palletsprojects.com/ |
|                   | WTForms       | https://wtforms.readthedocs.io/ |
|                   | flask-login   | https://flask-login.readthedocs.io/ |
|                   | Gunicorn      | https://gunicorn.org/ |
|                   | Apache        | https://httpd.apache.org/ |

## Architecture

indi-allsky utilizes python's multiprocessing library to enable parallelizing tasks so that image processing does not interfere with image aquisition, etc.

![](./content/indi-allsky-arch.svg)

## Configuration

All configuration is read from the database.  Almost all of the configuration is managed via the web interface.
You may use the config.py utility to manipulate the configuration from the command line.

https://github.com/aaronwmorris/indi-allsky/wiki/Configuration-Reference

## Tested Hardware

3-4 weeks of constant runtime with no intervention are common.  The only reason I restart my cameras are code updates (or power failures).

The hardware below has at least been plugged in and tested for correct detection and CFA decoding.

| Vendor   | Model               | Rating | Notes |
| -------- | ------------------- | ------ | ----- |
| ZWO      | ASI120MC-S          | B      | https://github.com/aaronwmorris/indi-allsky/wiki/ASI120MC-S-Camera-Issues |
| ZWO      | ASI290MM            | A      |       |
| ZWO      | ASI178MM            | A      |       |
| ZWO      | ASI178MC            | A      |       |
| ZWO      | ASI385MC            | A      |       |
| ZWO      | ASI071MC Pro        | A      |       |
| ZWO      | ASI183MM Pro        | A      |       |
| ZWO      | ASI183MC Pro        | A      |       |
| QHY      | QHY5LII-M           | A      |       |
| Svbony   | SV305               | B      | ~20% of frames require double the configured exposure time to complete. Likely a firmware bug. |
| Altair   | GPCAM3 290C         | A      | Needs [config](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config) for full resolution |
| Altair   | GPCAM3 224C         | A      | Needs [config](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config) for full resolution |
| Altair   | GPCAM2 290M         | A      |       |
| Touptek  | G3CMOS06300KPA (IMX178) | A  |       |
| Touptek  | G-1200-KMB          | A      |       |
| Player One   | Mars-C          | A      |       |
| Player One   | Neptune-C       | A      |       |
| Starlight Xpress | Superstar   | A      |       |
| Datyson  | T7C                 | A      | Using indi_asi_ccd driver<br />Recommend ASI120MC Linux compatibility firmware |
| Raspberry Pi | HQ Camera       | C      | https://github.com/aaronwmorris/indi-allsky/wiki/Raspberry-PI-HQ-Camera |
| Raspberry Pi | HQ Camera (libcamera) | A      | Minimum 1GB of memory is needed to process RAW images with dark calibration frames |
| Waveshare    | imx378 (libcamera)    | A      | Select libcamera_imx477 interface |
| ArduCam  | 64MP HawkEye        | A      | Recommend at least 4GB of RAM for full resolution 9152x6944.  [Options](https://github.com/aaronwmorris/indi-allsky/wiki/libcamera-enablement) available to reduce image size. |
| Canon    | 550D (Rebel T2i)    | A      | Camera resolution and pixel size have to be manually defined in config |
| Canon    | 1300D (Rebel T6)    | A      | Camera resolution and pixel size have to be manually defined in config |
| IP Cameras | indi_webcam_ccd   | B      | Needs [config](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config) for operation |
| Webcams  | indi_webcam_ccd     | D      | No gain controls.  Little control over image quality. |
| indi     | indi_simulator_ccd  |        | CCD Simulator.  Install GSC to generate sample images. |

If you have an INDI supported camera from a vendor not listed, open an enhancement request and I can work with you to support the camera.


## Gotchas
Common problems you might run into.

* The indi-allsky python processes consume ~500MB of RAM.
    * 1K (1920x1080) h.264 encoding with ffmpeg requires an additional ~500MB of RAM.  1GB of RAM should be the bare minimum system memory.  You should also have 100-500MB of additional swap space to prevent running out of memory during encoding.  2GB of RAM recommended.
    * 4K (3840x2160) h.264 encoding requires an additional 2+GB of RAM.  4GB of RAM recommended.
    * 8K resolution (ArduCam 64MP HawkEye) requires 8GB of RAM for full resolution video processing.
* In Raspbian 10 (legacy), the h.264 codec in ffmpeg has a maximum frame size of 4096×2304 (AVC level 5.1).  If your camera generates higher resolution images, you will need to scale the video  or use the Region of Interest (RoI) options to reduce the frame size.
    * NEW: indi-allsky now has the ability to scale the native resolution images during the ffmpeg encoding phase, so you do not need to pre-scale your images.
    * The RaspberryPi HQ camera has a bin1 image size of 4056x3040.  Setting IMAGE_SCALE to 75 in the config results in a image size of 3042x2280.  Alternatively, you can center crop the image using IMAGE_CROP_ROI set to [0, 368, 4056, 2672] for an image size of 4056×2304.
* ffmpeg in Raspbian 11 enables AVC level 6.0+ which permits h.264 resolutions up to 8192×4320 (you must have sufficient system memory)
    * https://en.wikipedia.org/wiki/Advanced_Video_Coding


## File Transfer

indi-allsky supports several file transfer methods.  Additional file transfer methods are planned such as direct to YouTube uploads.

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

## Alternatives

* Thomas Jacquin's Allsky
    * Free, Open source
    * Linux, SoC
    * https://github.com/thomasjacquin/allsky
* AllSkEye
    * Free version, Commercial option
    * Windows
    * https://allskeye.com/
* RPi Meteor Station
    * Free, Open source
    * Linux, SoC
    * https://github.com/CroatianMeteorNetwork/RMS
* Meteotux Pi
    * Free version, Commercial option
    * Linux, SoC
    * https://www.meteotuxpi.com/
* UFOCapture
    * Shareware, Commercial option
    * Windows
    * https://sonotaco.com/soft/e_index.html

## Commercial hardware

* Oculus All-Sky Cameras
    * https://www.sxccd.com/cameras/oculus-all-sky-cameras/
* Alcor System
    * https://www.alcor-system.com/new/AllSky/Alphea_camera.html

## Acknowledgements

* [Thomas Jacquin](https://github.com/thomasjacquin) - indi-allsky is heavily inspired by his [allsky](https://github.com/thomasjacquin/allsky) software.
* [Marco Gulino](https://github.com/GuLinux) - His examples from [indi-lite-tools](https://github.com/GuLinux/indi-lite-tools) were key to understanding how to work with pyindi-client
* [PixInsight](https://www.pixinsight.com/) - Various algorithms were used that are in the PixInsight documentation

