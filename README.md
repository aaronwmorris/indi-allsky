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


