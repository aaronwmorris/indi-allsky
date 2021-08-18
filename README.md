# Indi Allsky
indi-allsky is software used to manage a Linux-based All Sky Camera.

## Requirements
* A computer, such as a Raspberry Pi
* An INDI supported camera

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
1. Activate the indi-allsky python virtual environment
```
source virtualenv/indi-allsky/bin/activate
```
1. Start indi-allsky
```
./allsky.py -c config.json run
```

## Software Dependencies
indi-allsky itself is written in python, but python is just the glue between the different libraries, most of which are C code which makes indi-allsky extremely fast.

| Function          | Software      | URL |
| ----------------- | ------------- | --- |
| Camera interface  | INDI          | https://indilib.org/ |
|                   | pyindi-client | https://github.com/indilib/pyindi-client |
| Image processing  | OpenCV        | https://opencv.org/ |
|                   | opencv-python | https://github.com/opencv/opencv-python |
|                   | astropy       | https://www.astropy.org/ |
| Video processing  | ffmpeg        | https://www.ffmpeg.org/ |
| Astrometry        | pyephem       | https://rhodesmill.org/pyephem/ |
| File transfer     | pycurl        | http://pycurl.io/ |
|                   | paramiko      | http://www.paramiko.org/ |

## Architecture

indi-allsky utilizes python's multiprocessing library to enable parallelizing tasks so that image processes does not interfere with image aquisition, etc.

![](./content/indi-allsky-arch.svg)

## Configuration

All configuration is read from config.json.  You can find configuration examples in the examples/ folder.

| Setting             | Default     | Description |
| ------------------- | ----------- | ----------- |
| INDI_CONFIG_NIGHT   |             | (dict) Indi configuration parameters for night time |
| > GAIN_VALUE        |             | (int) Gain value (mainly for image text) |
| > BIN_VALUE         |             | (int) Binning value (for calculation |
| > PROPERTIES        |             | (dict) Indi properties |
| > SWITCHES          |             | (dict) Indi switches |
| INDI_CONFIG_NIGHT_MOONMODE |      | (dict) Indi configuration parameters for "moon mode" |
| INDI_CONFIG_DAY     |             | (dict) Indi configuration parameters for day time |
| CCD_EXPOSURE_MAX    | 15          | (seconds) Maximum exposure time |
| CCD_EXPOSURE_MIN    | Camera dependent | (seconds) Minimum exposure time |
| CCD_EXPOSURE_DEF    | 0.0001      | (seconds) Default/starting exposure |
| EXPOSURE_PERIOD     | 15          | (seconds) Time between beginning of each exposure |
| TARGET_ADU          | varies      | Target image brightness to calculate exposure time |
| TARGET_ADU_DEV      | varies      | Deviation +/- from target ADU to recalculate exposure time |
| ADU_ROI             | []          | Region of interest to calculate ADU (x1, y1, x2, y2) |
| LOCATION_LATITUDE   |             | (string) Your latitude for astrometric calculations |
| LOCATION_LONGITUDE  |             | (string) Your longitude for astrometric calculations |
| DAYTIME_CAPTURE     | false       | (bool) Perform day time image capture |
| DAYTIME_TIMELAPSE   | false       | (bool) Generate timelapse from day time images |
| DAYTIME_CONTRAST_ENHANCE | false  | (bool) Perform CLAHE contrast enhancement on day time images |
| NIGHT_CONTRAST_ENHANCE   | false  | (bool) Perform CLAHE contrast enhancement on night time images |
| NIGHT_SUN_ALT_DEG   | -6          | (degrees) Altitude of Sun to calculate beginning and end of night |
| NIGHT_MOONMODE_ALT_DEG   | 0      | (degrees) Altitude of Moon to enable night time "moon mode" |
| NIGHT_MOONMODE_PHASE     | 33     | (percent) Minimum illumination of Moon to enable night time "moon mode" |
| IMAGE_FILE_TYPE     | jpg         | (jpg|png) Default image type |
| IMAGE_FILE_COMPRESSION   |        | (dict) Default compression values for image types |
| IMAGE_FOLDER        |             | Base folder to save images |
| IMAGE_DEBAYER       | null        | OpenCV debayering algorithm |
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
