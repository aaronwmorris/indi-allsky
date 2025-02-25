#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset
shopt -s nullglob

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH


function catch_error() {
    echo
    echo
    echo "\`\`\`"  # markdown
    echo "###############"
    echo "###  ERROR  ###"
    echo "###############"
    echo
    echo "The script exited abnormally, please try to run again..."
    echo
    echo
    exit 1
}
trap catch_error ERR

function catch_sigint() {
    echo
    echo
    echo "\`\`\`"  # markdown
    echo "###############"
    echo "###  ERROR  ###"
    echo "###############"
    echo
    echo "The script was interrupted, please run the script again to finish..."
    echo
    echo
    exit 1
}
trap catch_sigint SIGINT


if [ ! -f "/etc/os-release" ]; then
    echo
    echo "Unable to determine OS from /etc/os-release"
    echo
    exit 1
fi

source /etc/os-release


DISTRO_ID="${ID:-unknown}"
DISTRO_VERSION_ID="${VERSION_ID:-unknown}"
CPU_ARCH=$(uname -m)
CPU_BITS=$(getconf LONG_BIT)
CPU_TOTAL=$(grep -c "^proc" /proc/cpuinfo)
MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk "{print \$2}")


if [ -f "/proc/device-tree/model" ]; then
    SYSTEM_MODEL=$(cat /proc/device-tree/model)
else
    SYSTEM_MODEL="Generic PC"
fi


if which indiserver >/dev/null 2>&1; then
    INDISERVER=$(which indiserver)
else
    INDISERVER="not found"
fi


SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.."
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD"


# go ahead and prompt for password
#sudo true


echo "#################################"
echo "### indi-allsky support info  ###"
echo "#################################"

sleep 3

echo "\`\`\`"  # markdown
echo
echo "Distribution: $DISTRO_ID"
echo "Release: $DISTRO_VERSION_ID"
echo "Arch: $CPU_ARCH"
echo "Bits: $CPU_BITS"
echo
echo "CPUs: $CPU_TOTAL"
echo "Memory: $MEM_TOTAL kB"
echo
echo "System: $SYSTEM_MODEL"


if [[ -d "/etc/stellarmate" ]]; then
    echo
    echo "Detected Stellarmate"
    if [[ -f "/etc/stellarmate/version" ]]; then
        head -n 1 /etc/stellarmate/version || true
    fi
    echo
elif [[ -f "/etc/astroberry.version" ]]; then
    echo
    echo "Detected Astroberry server"
    echo
fi


echo
uname -a

echo "Hostname"
hostname -f
hostname -A

echo
echo "Time"
date

echo
echo "System timezone"
cat /etc/timezone || true

echo
echo "Uptime"
uptime

echo
echo "Memory"
free

echo
echo "Filesystems"
df -k

echo
echo "sysctl info"
/usr/sbin/sysctl vm.swappiness

echo
echo "Thermal info"
for X in /sys/class/thermal/thermal_zone*; do
    [ -f "$X/type" ] && cat "$X/type"
    [ -f "$X/temp" ] && cat "$X/temp"
done

echo
echo "system python: $(python3 -V)"

echo
echo "indiserver: $INDISERVER"
echo


if [ -f "/etc/astroberry.version" ]; then
    echo "Detected Astroberry server"
    echo
fi

echo
echo "IP Info"
ip address

echo
echo "User info"
id
echo

echo
echo "gpsd user info"
id gpsd || true
echo

echo "Process info"
# shellcheck disable=SC2009
ps auxwww | grep indi | grep -v grep || true
echo

echo "Check for virtual sessions"
# shellcheck disable=SC2009
ps auxwww | grep -i "screen\|tmux\|byobu" | grep -v grep || true
echo

echo "USB info"
lsusb || true
echo
lsusb -t || true
echo

echo "USB Permissions"
find /dev/bus/usb -ls || true
echo

echo "video device Permissions"
ls -l /dev/video* || true
echo

echo "v4l info"
v4l2-ctl --list-devices || true
echo

echo "Module info"
lsmod || true
echo


echo "I2C info"
i2cdetect -y 1 || true
echo


echo "git status"
git status | head -n 100
echo


echo "git log"
git log -n 1 | head -n 100
echo


if pkg-config --exists libindi; then
    DETECTED_INDIVERSION=$(pkg-config --modversion libindi)
    echo "indi version: $DETECTED_INDIVERSION"
    echo
else
    echo "indi version: not detected"
    echo
fi


echo "indi packages"
dpkg -l | grep libindi || true
echo


echo "indi connections"
ss -ant | grep 7624 || true
echo


echo "Detected indi properties"
indi_getprop -v 2>&1 || true
echo


if pkg-config --exists libcamera; then
    DETECTED_LIBCAMERA=$(pkg-config --modversion libcamera)
    echo "libcamera version: $DETECTED_LIBCAMERA"
    echo
else
    echo "libcamera: not detected"
    echo
fi


echo "libcamera packages"
dpkg -l | grep -E "libcamera|rpicam" || true
echo

echo "libcamera cameras"
if which rpicam-hello >/dev/null 2>&1; then
    echo "rpicam-hello: $(which rpicam-hello)"
    rpicam-hello --list-cameras || true
    echo
elif which libcamera-hello >/dev/null 2>&1; then
    echo "libcamera-hello: $(which libcamera-hello)"
    libcamera-hello --list-cameras || true
    echo
else
    echo "libcamera-hello not available"
    echo
fi


echo "python packages"
dpkg -l | grep python || true
echo


if [ -d "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky" ]; then
    echo "Detected indi-allsky virtualenv"

    # shellcheck source=/dev/null
    source "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate"
    echo "virtualenv python: $(python3 -V)"
    echo "virtualenv PATH: $PATH"

    if which flask >/dev/null 2>&1; then
        echo "flask command: $(which flask)"
    else
        echo "flask: not found"
    fi

    echo
    echo "virtualenv python modules"
    pip freeze || true

    echo "\`\`\`"  # markdown


    echo
    echo "Flask config"
    echo "\`\`\`json"  # markdown
    # Remove all secrets from config
    # SQLALCHEMY_DATABASE_URI will contain passwords if using mysql
    jq --arg redacted "REDACTED" '.SQLALCHEMY_DATABASE_URI = $redacted | .SECRET_KEY = $redacted | .PASSWORD_KEY = $redacted' < /etc/indi-allsky/flask.json || true
    echo "\`\`\`"  # markdown


    echo
    echo "indi-allsky config (passwords redacted)"
    INDI_ALLSKY_CONFIG=$("${ALLSKY_DIRECTORY}/config.py" dump)


    # reduce lat/long precision
    LOCATION_LATITUDE=$(echo "$INDI_ALLSKY_CONFIG" | jq -r '.LOCATION_LATITUDE')
    LOCATION_LONGITUDE=$(echo "$INDI_ALLSKY_CONFIG" | jq -r '.LOCATION_LONGITUDE')

    INDI_ALLSKY_CONFIG=$(echo "$INDI_ALLSKY_CONFIG" | jq --argjson lat "$(printf '%0.0f' "$LOCATION_LATITUDE")" --argjson long "$(printf '%0.0f' "$LOCATION_LONGITUDE")" '.LOCATION_LATITUDE = $lat | .LOCATION_LONGITUDE = $long')


    echo "\`\`\`json"  # markdown
    # Remove all secrets from config
    echo "$INDI_ALLSKY_CONFIG" | jq --arg redacted "REDACTED" '.OWNER = $redacted | .FILETRANSFER.PASSWORD = $redacted | .FILETRANSFER.PASSWORD_E = $redacted | .S3UPLOAD.SECRET_KEY = $redacted | .S3UPLOAD.SECRET_KEY_E = $redacted | .MQTTPUBLISH.PASSWORD = $redacted | .MQTTPUBLISH.PASSWORD_E = $redacted | .SYNCAPI.APIKEY = $redacted | .SYNCAPI.APIKEY_E = $redacted | .PYCURL_CAMERA.PASSWORD = $redacted | .PYCURL_CAMERA.PASSWORD_E = $redacted | .TEMP_SENSOR.OPENWEATHERMAP_APIKEY = $redacted | .TEMP_SENSOR.OPENWEATHERMAP_APIKEY_E = $redacted | .TEMP_SENSOR.WUNDERGROUND_APIKEY = $redacted | .TEMP_SENSOR.WUNDERGROUND_APIKEY_E = $redacted | .TEMP_SENSOR.ASTROSPHERIC_APIKEY = $redacted | .TEMP_SENSOR.ASTROSPHERIC_APIKEY_E = $redacted | .TEMP_SENSOR.AMBIENTWEATHER_APIKEY = $redacted | .TEMP_SENSOR.AMBIENTWEATHER_APIKEY_E = $redacted | .TEMP_SENSOR.AMBIENTWEATHER_APPLICATIONKEY = $redacted | .TEMP_SENSOR.AMBIENTWEATHER_APPLICATIONKEY_E = $redacted | .TEMP_SENSOR.AMBIENTWEATHER_MACADDRESS = $redacted | .TEMP_SENSOR.AMBIENTWEATHER_MACADDRESS_E = $redacted | .TEMP_SENSOR.ECOWITT_APIKEY = $redacted | .TEMP_SENSOR.ECOWITT_APIKEY_E = $redacted | .TEMP_SENSOR.ECOWITT_APPLICATIONKEY = $redacted | .TEMP_SENSOR.ECOWITT_APPLICATIONKEY_E = $redacted | .TEMP_SENSOR.ECOWITT_MACADDRESS = $redacted | .TEMP_SENSOR.ECOWITT_MACADDRESS_E = $redacted |.TEMP_SENSOR.MQTT_PASSWORD = $redacted | .TEMP_SENSOR.MQTT_PASSWORD_E = $redacted | .ADSB.PASSWORD = $redacted | .ADSB.PASSWORD_E = $redacted'

    deactivate
    echo
else
    echo "indi-allsky virtualenv is not created"
    echo
fi
echo "\`\`\`"  # markdown


echo
echo "indi-allky log errors"
echo "\`\`\`"  # markdown
grep -i "error" /var/log/indi-allsky/indi-allsky.log | tail -n 30 || true
echo "\`\`\`"  # markdown


echo
echo "#################################"
echo "###     end support info      ###"
echo "#################################"
