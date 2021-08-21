# Indi Allsky
indi-allsky is software used to manage a Linux-based All Sky Camera using the INDI framework.  Theoretically, any INDI supported CCD/CMOS camera should be usable.

## Requirements
* A computer running a modern Linux distribution, such as a Raspberry Pi
    * Multicore is recommended
        * ARM
        * x86_64
    * 1GB RAM  (512MB might work, but may require additional swap space)
    * 64GB of storage minimum to store 2 months of videos and 30 days of JPEG images.
    * (Optional) Internet connectivity for image uploading
* An INDI supported camera
    * CPU architecture support varies between camera manufacturers

MacOS support is theoretically possible, but not tested.  Not all INDI cameras have Mac firmwares available.

## Installation
1. Install git
```
apt-get install git
```
1. Clone the indi-allsky git repository
```
git clone https://github.com/aaronwmorris/indi-allsky.git
```
1. Navigate to the indi-allky sub-directory
```
cd indi-allsky.git
```
1. Run setup.sh to install the relevant software
```
./setup.sh
```
 * Note:  You may be prompted for a password for sudo
1. Edit the config.json file to customize your settings
1. Start the software
```
sudo systemctl start indiserver
sudo systemctl start indi-allsky
```

### Manual operation
1. Stop indi-allsky service
```
sudo systemctl stop indi-allsky
```
1. Activate the indi-allsky python virtual environment
```
source virtualenv/indi-allsky/bin/activate
```
1. Start indi-allsky
```
./allsky.py -c config.json run
```

### Dark frames
1. Stop indi-allsky service (above)
1. Activate the indi-allsky python virtual environment (above)
1. Start indi-allsky with darks option
```
./allsky.py -c config.json darks
```

* Darks will be generated in 1 second increments for the configured gain and binmode for night, moonmode, and day frames.
* This operation can take a while depending on your maximum exposure.
    * 15 second maximum exposure:  ~10 minutes
    * 60 second maximum exposure:  a really long time

### Web Interfaces

Some very simple web pages are included to view images.  HTML5 canvas and javascript are utilized for some simple interactivity.

| File                | Description |
| ------------------- | ----------- |
| latest.html         | The latest image is loaded every 15 seconds and displayed.  Setting configured in settings_latest.js |
| loop.html           | A set of the latest images are loaded and displayed in a loop (like a GIF).  Settings configured in settings_loop.js |
| loop_realtime.html  | A loop is slowly built dynamically with the latest images loaded at regular intervals.  Settings configured in settings_loop.js |


## Performance

indi-allsky itself is written in python, but python is just the glue between the different libraries, most of which are C based which makes indi-allsky extremely fast.  A 1920 x 1080 image can be dark frame calibrated, debayered, histogram processed, text applied, and compressed to a JPG in less than 0.5 seconds on Raspberry Pi 3 class hardware.  PNG processing is a little more taxing, but usually only takes a few seconds.

ffmpeg video processing is considerably more expensive.  A 2 minute x264 encoded video compiled from 3,000 frames requires ~20 minutes on Raspberry Pi 3 (4 core) hardware.  Encoding takes place in a separate process from image aqcuisition and image processing and is run at the lowest CPU priority so image acquision is never impacted.

## Software Dependencies

| Function          | Software      | URL |
| ----------------- | ------------- | --- |
| Camera interface  | INDI          | https://indilib.org/ |
|                   | pyindi-client | https://github.com/indilib/pyindi-client |
| Image processing  | OpenCV        | https://opencv.org/ |
|                   | opencv-python | https://github.com/opencv/opencv-python |
|                   | astropy       | https://www.astropy.org/ |
|                   | numpy         | https://numpy.org/ |
| Video processing  | ffmpeg        | https://www.ffmpeg.org/ |
| Astrometry        | pyephem       | https://rhodesmill.org/pyephem/ |
| File transfer     | pycurl        | http://pycurl.io/ |
|                   | paramiko      | http://www.paramiko.org/ |

## Architecture

indi-allsky utilizes python's multiprocessing library to enable parallelizing tasks so that image processing does not interfere with image aquisition, etc.

![](./content/indi-allsky-arch.svg)

## Configuration

All configuration is read from config.json.  You can find configuration examples in the examples/ folder.

| Setting             | Default     | Description |
| ------------------- | ----------- | ----------- |
| CCD_CONFIG          |             | (dict) Indi configuration parameters for CCD |
| > NIGHT > GAIN      |             | (int) Gain for night time |
| > NIGHT > BINNING   |             | (int) Bin mode for night time |
| > MOONMODE > GAIN    |            | (int) Gain for moon mode|
| > MOONMODE > BINNING |            | (int) Bin mode for moon mode|
| > DAY > GAIN        |             | (int) Gain for day time |
| > DAY > BINNING     |             | (int) Bin mode for day time |
| INDI_CONFIG_DEFAULTS |            | (dict) Indi default configuration parameters |
| > PROPERTIES        |             | (dict) Indi properties |
| > SWITCHES          |             | (dict) Indi switches |
| CCD_EXPOSURE_MAX    | 15          | (seconds) Maximum exposure time |
| CCD_EXPOSURE_MIN    | Auto detected | (seconds) Minimum exposure time |
| CCD_EXPOSURE_DEF    | 0.0001      | (seconds) Default/starting exposure |
| EXPOSURE_PERIOD     | 15          | (seconds) Time between beginning of each exposure |
| TARGET_ADU          | varies      | (int) Target image brightness to calculate exposure time |
| TARGET_ADU_DEV      | 10          | (int) Deviation +/- from target ADU to recalculate exposure time |
| ADU_ROI             | []          | (array) Region of interest to calculate ADU (x1, y1, x2, y2) - Note: ROI calculated using bin 1 coordinates, scaled for bin value |
| LOCATION_LATITUDE   |             | (string) Your latitude for astrometric calculations |
| LOCATION_LONGITUDE  |             | (string) Your longitude for astrometric calculations |
| DAYTIME_CAPTURE     | false       | (bool) Perform day time image capture |
| DAYTIME_TIMELAPSE   | false       | (bool) Generate timelapse from day time images |
| DAYTIME_CONTRAST_ENHANCE | false  | (bool) Perform CLAHE contrast enhancement on day time images |
| NIGHT_CONTRAST_ENHANCE   | false  | (bool) Perform CLAHE contrast enhancement on night time images |
| NIGHT_SUN_ALT_DEG   | -6          | (degrees) Altitude of Sun to calculate beginning and end of night |
| NIGHT_MOONMODE_ALT_DEG   | 0      | (degrees) Altitude of Moon to enable night time "moon mode" |
| NIGHT_MOONMODE_PHASE     | 33     | (percent) Minimum illumination of Moon to enable night time "moon mode" |
| IMAGE_FILE_TYPE     | jpg         | (string) Image output type, jpg or png |
| IMAGE_FILE_COMPRESSION   |        | (dict) Default compression values for image types |
| IMAGE_FOLDER        |             | (string) Base folder to save images |
| IMAGE_DEBAYER       | Auto detected | (string) OpenCV debayering algorithm |
| IMAGE_FLIP_V        | false       | (bool) Flip images vertically |
| IMAGE_FLIP_H        | false       | (bool) Flip images horizontally |
| IMAGE_SCALE_PERCENT | null        | (percent) Image scaling factor |
| IMAGE_EXPIRE_DAYS   | 30          | (days) Number of days to keep original images before deleting |
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
| ORB_PROPERTIES      |             | (dict) Sun and moon org drawing properties |
| > RADIUS            | 9           | (pixels) Radius of orbs |
| > SUN_COLOR         | [0, 255, 255]   | (array) R, G, B Color of sun orb |
| > MOON_COLOR        | [255, 255, 255] | (array) R, G, B Color of moon orb |
| FILETRANSFER        |             | (dict) File tranfer configuration |
| > CLASSNAME         |             | (str) File transfer class |
| > HOST              |             | (str) Hostname for file transfer |
| > PORT              | null        | (int) Port for file transfer (null for protocol default) |
| > USERNAME          |             | (str) Username for file tranfer |
| > PASSWORD          |             | (str) Password for file tranfer |
| > TIMEOUT           | 5.0         | (float) Timeout for file transfer before failing |
| > REMOTE_IMAGE_NAME | latest.{0}  | (str) Python template for remote file name of latest image, extension is automatically selected from IMAGE_FILE_TYPE |
| REMOTE_IMAGE_FOLDER |             | (str) Remote folder to upload latest image |
| REMOTE_VIDEO_FOLDER |             | (str) Remote folder to upload time lapse videos |
| UPLOAD_IMAGE        | 0           | (int) Upload latest image every X frames |
| UPLOAD_VIDEO        | false       | (bool) Enable timelapse video uploads |

### Moon mode

This is a special night time operating mode intended to reduce gain when the moon is more illuminated and above the horizon


## Tested Hardware

I have extensively tested the ZWO ASI290MM and the Svbony SV305.  3-4 weeks of steady runtime with no intervention are common.  The only reason I restart my cameras are code updates (or power failures).

The hardware below has at least been plugged in and tested for correct detection and CFA decoding.

| Vendor   | Model           | Notes |
| -------- | --------------- | ----- |
| Svbony   | SV305           | 40% of frames require double the configured exposure time to complete.  Likely a firmware bug. |
| ZWO      | ASI290MM        |       |
| ZWO      | ASI178MM        |       |
| ZWO      | ASI178MC        |       |
| ZWO      | ASI071MC Pro    |       |
| ZWO      | ASI183MM Pro    |       |
| ZWO      | ASI183MC Pro    |       |


## File Transfer

indi-allsky supports several file transfer methods.  Additional file transfer methods are planned such as direct to YouTube uploads.

| Protocol | Class Name    | Port | Description |
| -------- | ------------- | ---- | ----------- |
| ftp      | pycurl_ftp    | 21   | FTP via pycurl |
|          | python_ftp    | 21   | FTP via ftplib |
| ftpes    | pycurl_ftpes  | 21   | FTPS (explicit) via pycurl |
|          | python_ftpes  | 21   | FTPS (explicit) via ftplib |
| ftps     | pycurl_ftps   | 990  | FTPS (implicit) via pycurl |
| sftp     | pycurl_sftp   | 22   | SFTP via pycurl |
|          | paramiko_sftp | 22   | SFTP via paramiko |

## To Do

* Keogram generation
* 16bit image handling

## Acknowledgements

* [Thomas Jacquin](https://github.com/thomasjacquin) - indi-allsky is heavily inspired by his [allsky](https://github.com/thomasjacquin/allsky) software.
* [Marco Gulino](https://github.com/GuLinux) - His examples from [indi-lite-tools](https://github.com/GuLinux/indi-lite-tools) were key to understanding how to work with pyindi-client

