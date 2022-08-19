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
* Timelapse video generation
* Network file transfers - Upload images and videos to remote site
* Publish data to an MQTT service for monitoring
* Keograms
* Star Trails
* Automatic meteor/plane/satellite detection
* Images display local hour angle of sun and moon
* Moon mode - reduced gain when the moon is overhead
* Remote INDI server operation - operate camera remotely over the network
* Pseudo-Sky Quality Meter - Use your all sky camera to measure sky brightness/quality
* SQLite database stores image metadata

## Requirements
* A computer running a modern Linux distribution, such as a Raspberry Pi
    * Multicore is recommended
        * ARM
        * x86_64
    * 2GB RAM recommended, 1GB minimum
        * 512MB is adequate for image acquisition, but not enough to generate timelapse videos with ffmpeg
    * 64GB of storage minimum to store 2 months of videos and 30 days of JPEG images.
    * (Optional) Internet connectivity for image uploading
* An INDI supported camera
    * CPU architecture support varies between camera manufacturers
* NEW: A libcamera supported camera

### Distibution support
| Distribution          | Arch           | Note |
| --------------------- | -------------- | ---- |
| Raspbian 11 64-bit    | arm64          | Compile indi with build_indi.sh<br />Use libcamera for Raspberry PI HQ camera |
| Raspbian 11 32-bit    | armhf          | Compile indi with build_indi.sh<br />The rawpy module is not availble on 32-bit Arm, therefore libcamera image processing is not available |
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

Proper libcamera support is only working on Raspbian 11 64-bit on Raspberry Pi 3 & 4


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

## Star Detection
indi-allsky utilizes OpenCV pattern matching to detect and count the number of stars in the view.  Star counts are a good objective measurement of sky conditions.

Star and meteor detection support using detection masks to customize your Region of Interest if there are obstructions in your view.
https://github.com/aaronwmorris/indi-allsky/wiki/Detection-Masks

## Meteor Detection
Using OpenCV Canny edge detection and Hough Line Transform, indi-allsky is able to perform basic line detection to detect meteor and fireball trails in the view.  Airplane and satellite trails are also detected using this method.  Images are tagged with an asterisk in the image viewer if a trail has been detected.

## Web Interface

The indi-allsky web interface is built on the Flask MVC framework.  It is designed to be a dashboard for your sky.  Included is the ability to fully manage the camera configuration without having to manually edit from the command line.

The default credentials for accessing the web interface are user `admin` and password `secret`

An unauthenticated public access URL is also available at https://raspberrypi.local/indi-allsky/public  (actual hostname may vary)

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


## Performance

indi-allsky itself is written in python, but python is just the glue between the different libraries, most of which are C based which makes indi-allsky extremely fast.  A 1920 x 1080 image can be dark frame calibrated, debayered, histogram processed, text applied, and compressed to a JPG in less than 0.5 seconds on Raspberry Pi 3 class hardware.  PNG processing is a little more taxing, but usually only takes a few seconds.

ffmpeg video processing is considerably more expensive.  A 2 minute x264 encoded video compiled from 3,000 frames requires ~20 minutes on Raspberry Pi 3 (4 core) hardware.  Encoding takes place in a separate process from image aqcuisition and image processing and is run at the lowest CPU priority so image acquision is never impacted.

## Software Dependencies

| Function          | Software      | URL |
| ----------------- | ------------- | --- |
| Camera interface  | INDI          | https://indilib.org/ |
|                   | pyindi-client | https://github.com/indilib/pyindi-client |
|                   | libcamera     | https://libcamera.org/ |
| Image processing  | OpenCV        | https://opencv.org/ |
|                   | opencv-python | https://github.com/opencv/opencv-python |
|                   | astropy       | https://www.astropy.org/ |
|                   | ccdproc       | https://ccdproc.readthedocs.io/ |
|                   | numpy         | https://numpy.org/ |
| Video processing  | ffmpeg        | https://www.ffmpeg.org/ |
| Astrometry        | pyephem       | https://rhodesmill.org/pyephem/ |
| File transfer     | pycurl        | http://pycurl.io/ |
|                   | paramiko      | http://www.paramiko.org/ |
|                   | paho-mqtt     | https://www.eclipse.org/paho/ |
| Database          | SQLite        | https://www.sqlite.org/ |
|                   | SQLAlchemy    | https://www.sqlalchemy.org/ |
|                   | alembic       | https://alembic.sqlalchemy.org/ |
| Web interface     | Flask         | https://flask.palletsprojects.com/ |
|                   | WTForms       | https://wtforms.readthedocs.io/ |
|                   | Gunicorn      | https://gunicorn.org/ |
|                   | Apache        | https://httpd.apache.org/ |

## Architecture

indi-allsky utilizes python's multiprocessing library to enable parallelizing tasks so that image processing does not interfere with image aquisition, etc.

![](./content/indi-allsky-arch.svg)

## Configuration

All configuration is read from /etc/indi-allsky/config.json .  You can find configuration examples in the examples/ folder.

| Setting             | Default     | Description |
| ------------------- | ----------- | ----------- |
| CAMERA_INTERFACE    | indi        | (str) Default camera interface |
| INDI_SERVER         | localhost   | (str) Hostname for INDI server |
| INDI_PORT           | 7624        | (int) Port for INDI server |
| CCD_CONFIG          |             | (dict) Indi configuration parameters for CCD |
| > NIGHT > GAIN      |             | (int) Gain/ISO for night time |
| > NIGHT > BINNING   |             | (int) Bin mode for night time |
| > MOONMODE > GAIN    |            | (int) Gain/ISO for moon mode|
| > MOONMODE > BINNING |            | (int) Bin mode for moon mode|
| > DAY > GAIN        |             | (int) Gain/ISO for day time |
| > DAY > BINNING     |             | (int) Bin mode for day time |
| INDI_CONFIG_DEFAULTS |            | (dict) Indi default configuration parameters |
| > PROPERTIES        |             | (dict) Indi properties |
| > SWITCHES          |             | (dict) Indi switches |
| CCD_EXPOSURE_MAX    | 15.0        | (float) Maximum exposure time |
| CCD_EXPOSURE_MIN    | Auto detected | (float) Minimum exposure time |
| CCD_EXPOSURE_DEF    | CCD_EXPOSURE_MIN | (float) Default/starting exposure |
| EXPOSURE_PERIOD     | 15.0        | (float) Seconds between beginning of each exposure (Night) |
| EXPOSURE_PERIOD_DAY | 15.0        | (float) Seconds between beginning of each exposure (Day) |
| FOCUS_MODE          | false       | (bool) Focus mode is used to take exposures as quickly as possible to aid in focusing |
| FOCUS_DELAY         | 4.0         | (float) Delay between exposures during focus mode |
| AUTO_WB             | false       | (bool) Automatic white balance adjustment |
| WBR_FACTOR          | 1.0         | (float) Red Balance Adjustment Factor |
| WBG_FACTOR          | 1.0         | (float) Green Balance Adjustment Factor |
| WBB_FACTOR          | 1.0         | (float) Blue Balance Adjustment Factor |
| TEMP_DISPLAY        | c           | (str) Temperature display conversion c = celcius, f = fahrenheit, k = kelvin |
| TARGET_ADU          | varies      | (int) Target image brightness to calculate exposure time |
| TARGET_ADU_DEV      | 10          | (int) Deviation +/- from target ADU to recalculate exposure time (night) |
| TARGET_ADU_DEV_DAY  | 20          | (int) Deviation +/- from target ADU to recalculate exposure time (day) |
| ADU_ROI             | []          | (array) Region of interest to calculate ADU (x1, y1, x2, y2) - Note: ROI calculated using bin 1 coordinates, scaled for bin value |
| DETECT_STARS        | true        | (bool) Enable star detection |
| DETECT_STARS_THOLD  | 0.6         | (float) Star detection threshold |
| DETECT_METEORS      | false       | (bool) Enable meteor detection |
| DETECT_MASK         |             | (str) Image file to use for detection mask |
| DETECT_DRAW         | false       | (bool) Draw detected objects on original image |
| SQM_ROI             | []          | (array) Region of interest for SQM and Star detection |
| LOCATION_LATITUDE   |             | (float) Your latitude for astrometric calculations |
| LOCATION_LONGITUDE  |             | (float) Your longitude for astrometric calculations |
| TIMELAPSE_ENABLE    | true        | (bool) Enable timelapse, keogram, and star trail creation |
| DAYTIME_CAPTURE     | true        | (bool) Perform day time image capture |
| DAYTIME_TIMELAPSE   | true        | (bool) Generate timelapse from day time images |
| DAYTIME_CONTRAST_ENHANCE | false  | (bool) Perform CLAHE contrast enhancement on day time images |
| NIGHT_CONTRAST_ENHANCE   | false  | (bool) Perform CLAHE contrast enhancement on night time images |
| NIGHT_SUN_ALT_DEG   | -6          | (degrees) Altitude of Sun to calculate beginning and end of night |
| NIGHT_MOONMODE_ALT_DEG   | 0      | (degrees) Altitude of Moon to enable night time "moon mode" |
| NIGHT_MOONMODE_PHASE     | 33     | (percent) Minimum illumination of Moon to enable night time "moon mode" |
| WEB_EXTRA_TEXT      |             | (str) File to include in web info box |
| KEOGRAM_ANGLE       | 0           | (float) Angle of image rotation for keogram generation |
| KEOGRAM_H_SCALE     | 100         | (int) Horizontal scaling of keograms |
| KEOGRAM_V_SCALE     | 33          | (int) Vertical scaling of keograms |
| KEOGRAM_LABEL       | true        | (bool) Label keogram timeline |
| STARTRAILS_MAX_ADU  | 50          | (int) Max ADU/brightness of image to be included in star trails |
| STARTRAILS_MASK_THOLD    | 190    | (int) Minimum threshold for star mask generation for star trails |
| STARTRAILS_PIXEL_THOLD   | 1.0    | (float) Cutoff percentage of pixels in mask to eliminate images from star trails |
| IMAGE_FILE_TYPE     | jpg         | (string) Image output type, jpg or png |
| IMAGE_FILE_COMPRESSION   |        | (dict) Default compression values for image types |
| IMAGE_FOLDER        |             | (string) Base folder to save images |
| IMAGE_LABEL         | true        | (bool) Add image timestamps labels |
| IMAGE_EXTRA_TEXT    |             | (string) Filename containing extra text for image |
| IMAGE_DEBAYER       | Auto detected | (string) OpenCV debayering algorithm |
| NIGHT_GRAYSCALE     | false       | Convert image to grayscale at night|
| DAYTIME_GRAYSCALE   | false       | Convert image to grayscale during day |
| IMAGE_FLIP_V        | true        | (bool) Flip images vertically |
| IMAGE_FLIP_H        | true        | (bool) Flip images horizontally |
| IMAGE_SCALE         | 100         | (percent) Image scaling factor |
| IMAGE_CROP_ROI      | []          | (array) Region of interest to crop image (x1, y1, x2, y2) |
| IMAGE_SAVE_FITS     | false       | (bool) Save raw FITS image data |
| IMAGE_EXPORT_RAW    | ""          | (string) Export raw images this file format |
| IMAGE_EXPORT_FOLDER |             | (string) Folder to export raw tiff files |
| IMAGE_EXPIRE_DAYS   | 30          | (days) Number of days to keep original images before deleting |
| TIMELAPSE_EXPIRE_DAYS    | 365    | (days) Number of days to keep timelapse, keogram, and star trails before deleting |
| FFMPEG_FRAMERATE    | 25          | (fps) Target frames per second for timelapse videos |
| FFMPEG_BITRATE      | 2500k       | (kilobytes) Target data rate for timelapse video compression |
| TEXT_PROPERTIES     |             | (dict) Default text properties (font, size, etc) |
| > FONT_FACE         |             | (str) OpenCV font name |
| > FONT_HEIGHT       | 30          | (pixels) Font height |
| > FONT_X            | 15          | (pixels) Font X offset |
| > FONT_Y            | 30          | (pixels) Font Y offset |
| > FONT_COLOR        | [200, 200, 200] | (array) R, G, B font color values |
| > FONT_AA           | LINE_AA     | (str) OpenCV antialiasing algorighm |
| > FONT_SCALE        | 0.8         | (float) Font scaling factor |
| > FONT_THICKNESS    | 1           | (int) Font weight |
| > FONT_OUTLINE      | true        | (bool) Enable black outline of text |
| > DATE_FORMAT       | %Y%m%d %H:%M:%S | (str) Date string format |
| ORB_PROPERTIES      |             | (dict) Sun and moon org drawing properties |
| > MODE              | ha          | (str) Orb Mode - ha = Hour Angle, az = Azimuth, alt = Altitude , off = Off|
| > RADIUS            | 9           | (pixels) Radius of orbs |
| > SUN_COLOR         | [0, 255, 255]   | (array) R, G, B Color of sun orb |
| > MOON_COLOR        | [255, 255, 255] | (array) R, G, B Color of moon orb |
| FILETRANSFER        |             | (dict) File tranfer configuration |
| > CLASSNAME         |             | (str) File transfer class |
| > HOST              |             | (str) Hostname for file transfer |
| > PORT              | 0           | (int) Port for file transfer (null for protocol default) |
| > USERNAME          |             | (str) Username for file tranfer |
| > PASSWORD          |             | (str) Password for file tranfer |
| > TIMEOUT           | 5.0         | (float) Timeout for file transfer before failing |
| > REMOTE_IMAGE_NAME | latest.{0}  | (str) Python template for remote file name of latest image, extension is automatically selected from IMAGE_FILE_TYPE |
| > REMOTE_IMAGE_FOLDER        |      | (str) Remote folder to upload latest image |
| > REMOTE_METADATA_NAME       | latest_metadata.json | (str) Filename for remote metadata upload |
| > REMOTE_METADATA_FOLDER     |      | (str) Remote folder to upload metadata |
| > REMOTE_VIDEO_FOLDER        |      | (str) Remote folder to upload time lapse videos |
| > REMOTE_KEOGRAM_FOLDER      |      | (str) Remote folder to upload keograms |
| > REMOTE_STARTRAIL_FOLDER    |      | (str) Remote folder to upload star trails |
| > REMOTE_ENDOFNIGHT_FOLDER   |      | (str) Remote folder to upload Allsky EndOfNight data |
| > UPLOAD_IMAGE        | 0           | (int) Upload latest image every X frames |
| > UPLOAD_METADATA     | false       | (bool) Enable upload of image metadata |
| > UPLOAD_VIDEO        | false       | (bool) Enable timelapse video uploads |
| > UPLOAD_KEOGRAM      | false       | (bool) Enable keogram uploads |
| > UPLOAD_STARTRAIL    | false       | (bool) Enable star trail upload |
| > UPLOAD_ENDOFNIGHT   | false       | (bool) Enable EndOfNight data upload.  This is the data.json file for https://github.com/thomasjacquin/allsky-website |
| MQTTPUBLISH           |             | (dict) MQTT configuration |
| > ENABLE              | false       | (bool) Enable MQTT publishing |
| > TRANSPORT           | tcp         | (str) MQTT Transport - tcp or websockets |
| > HOST                |             | (str) MQTT/Mosquitto server |
| > PORT                | 8883        | (int) MQTT port, 1883 = standard, 8883 = TLS |
| > USERNAME            |             | (str) MQTT user |
| > PASSWORD            |             | (str) MQTT password |
| > BASE_TOPIC          | indi-allsky | (str) Base topic for MQ messages |
| > QOS                 | 0           | (int) MQTT QoS for messages |
| > TLS                 | true        | (bool) Use TLS for MQTT connection |
| > CERT_BYPASS         | true        | (bool) Bypass certificate validation for MQTT connection |

## Tested Hardware

I have extensively tested the ZWO ASI290MM and the Svbony SV305.  3-4 weeks of steady runtime with no intervention are common.  The only reason I restart my cameras are code updates (or power failures).

The hardware below has at least been plugged in and tested for correct detection and CFA decoding.

| Vendor   | Model               | Rating | Notes |
| -------- | ------------------- | ------ | ----- |
| Svbony   | SV305               | B      | ~20% of frames require double the configured exposure time to complete. Likely a firmware bug. |
| ZWO      | ASI120MC-S          | B      | https://github.com/aaronwmorris/indi-allsky/wiki/ASI120MC-S-Camera-Issues |
| ZWO      | ASI290MM            | A      |       |
| ZWO      | ASI178MM            | A      |       |
| ZWO      | ASI178MC            | A      |       |
| ZWO      | ASI385MC            | A      |       |
| ZWO      | ASI071MC Pro        | A      |       |
| ZWO      | ASI183MM Pro        | A      |       |
| ZWO      | ASI183MC Pro        | A      |       |
| QHY      | QHY5LII-M           | A      |       |
| Altair   | GPCAM2 290M         | A      |       |
| Touptek  | G-1200-KMB          | A      |       |
| Starlight Xpress | Superstar   | A      |       |
| Player One   | Mars-C          | A      |       |
| Datyson  | T7C                 | A      | Using indi_asi_ccd driver<br />Recommend ASI120MC Linux compatibility firmware |
| Raspberry Pi | HQ Camera       | C      | https://github.com/aaronwmorris/indi-allsky/wiki/Raspberry-PI-HQ-Camera |
| Raspberry Pi | HQ Camera (libcamera) | A      | |
| Canon    | 550D (Rebel T2i)    | A      | Camera resolution and pixel size have to be manually defined in config |
| Canon    | 1300D (Rebel T6)    | A      | Camera resolution and pixel size have to be manually defined in config |
| Generic  | indi_webcam_ccd     | D      | No gain controls.  Little control over image quality. |
| indi     | indi_simulator_ccd  |        | CCD Simulator.  Install GSC to generate sample images. |

If you have an INDI supported camera from a vendor not listed, open an enhancement request and I can work with you to support the camera.


## Gotchas
Common problems you might run into.

* The indi-allsky python processes consume ~500MB of RAM.
    * 1K (1920x1080) x264 encoding with ffmpeg requires an additional ~500MB of RAM.  1GB of RAM should be the bare minimum system memory.  You should also have 100-200MB of additional swap space to prevent running out of memory during encoding.
    * 4K (3840x2160) x264 encoding requires an additional 2+GB of RAM.  4GB of RAM should be the minimum system memory.
* The x264 codec is has a maximum frame size of 4096×2304.  If your camera generates images larger than this, you will need to scale the frames or use the Region of Interest (RoI) options to reduce the frame size.
    * The RaspberryPi HQ camera has a bin1 image size of 4056x3040.  Setting IMAGE_SCALE to 75 in the config results in a image size of 3042x2280.  Alternatively, you can center crop the image using IMAGE_CROP_ROI set to [0, 368, 4056, 2672] for an image size of 4056×2304.


## File Transfer

indi-allsky supports several file transfer methods.  Additional file transfer methods are planned such as direct to YouTube uploads.

| Protocol       | Class Name          | Port | Description |
| -------------- | ------------------- | ---- | ----------- |
| ftp            | pycurl_ftp          | 21   | FTP via pycurl |
|                | python_ftp          | 21   | FTP via ftplib |
| ftpes          | pycurl_ftpes        | 21   | FTPS (explicit) via pycurl |
|                | python_ftpes        | 21   | FTPS (explicit) via ftplib |
| ftps           | pycurl_ftps         | 990  | FTPS (implicit) via pycurl |
| sftp           | pycurl_sftp         | 22   | SFTP via pycurl |
|                | paramiko_sftp       | 22   | SFTP via paramiko |
| webdav (https) | pycurl_webdav_https | 443  | HTTPS PUT via pycurl |

## MQTT Publishing

indi-allsky supports publishing all sky data to an MQTT service for monitoring.

For more info, see the wiki page: https://github.com/aaronwmorris/indi-allsky/wiki/MQTT-Broker-Publishing

## To Do

* Additional camera vendor support

## Acknowledgements

* [Thomas Jacquin](https://github.com/thomasjacquin) - indi-allsky is heavily inspired by his [allsky](https://github.com/thomasjacquin/allsky) software.
* [Marco Gulino](https://github.com/GuLinux) - His examples from [indi-lite-tools](https://github.com/GuLinux/indi-lite-tools) were key to understanding how to work with pyindi-client

