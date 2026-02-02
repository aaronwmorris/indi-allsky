#!/bin/bash

#set -x  # command tracing
#set -o errexit  # replace by trapping ERR
#set -o nounset  # problems with python virtualenvs
shopt -s nullglob

PATH=/usr/bin:/bin
export PATH


### Non-interactive options example ###
#export INDIALLSKY_CAMERA_INTERFACE=indi
#export INDIALLSKY_INSTALL_INDI=true
#export INDIALLSKY_INSTALL_LIBCAMERA=false
#export INDIALLSKY_INSTALL_INDISERVER=true
#export INDIALLSKY_HTTP_PORT=80
#export INDIALLSKY_HTTPS_PORT=443
#export INDIALLSKY_INDI_PORT=7624
#export INDIALLSKY_TIMEZONE="America/New_York"
#export INDIALLSKY_INDI_VERSION=1.9.9
#export INDIALLSKY_CCD_DRIVER=indi_simulator_ccd
#export INDIALLSKY_GPS_DRIVER=None
#export INDIALLSKY_FLASK_AUTH_ALL_VIEWS=true
#export INDIALLSKY_WEB_USER=user@example.org
#export INDIALLSKY_WEB_PASS=password
#export INDIALLSKY_WEB_NAME="First Last"
#export INDIALLSKY_WEB_EMAIL=user@example.org
###


#### config ####
INDI_DRIVER_PATH="/usr/bin"

INDISERVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"
UPGRADE_ALLSKY_SERVICE_NAME="upgrade-indi-allsky"

ALLSKY_ETC="/etc/indi-allsky"
DOCROOT_FOLDER="/var/www/html"
HTDOCS_FOLDER="${DOCROOT_FOLDER}/allsky"

DB_FOLDER="/var/lib/indi-allsky"
DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"
SQLALCHEMY_DATABASE_URI="sqlite:///${DB_FILE}"
MIGRATION_FOLDER="$DB_FOLDER/migrations"

# mysql support is not ready
USE_MYSQL_DATABASE="${INDIALLSKY_USE_MYSQL_DATABASE:-false}"

CAMERA_INTERFACE="${INDIALLSKY_CAMERA_INTERFACE:-}"

OS_PACKAGE_UPGRADE="${INDI_ALLSKY_OS_PACKAGE_UPGRADE:-}"

INSTALL_INDI="${INDIALLSKY_INSTALL_INDI:-true}"
INSTALL_LIBCAMERA="${INDIALLSKY_INSTALL_LIBCAMERA:-false}"

INSTALL_INDISERVER="${INDIALLSKY_INSTALL_INDISERVER:-}"
INDI_VERSION="${INDIALLSKY_INDI_VERSION:-}"

CCD_DRIVER="${INDIALLSKY_CCD_DRIVER:-}"
GPS_DRIVER="${INDIALLSKY_GPS_DRIVER:-}"

HTTP_PORT="${INDIALLSKY_HTTP_PORT:-80}"
HTTPS_PORT="${INDIALLSKY_HTTPS_PORT:-443}"
INDI_PORT="${INDIALLSKY_INDI_PORT:-7624}"

FLASK_AUTH_ALL_VIEWS="${INDIALLSKY_FLASK_AUTH_ALL_VIEWS:-}"
WEB_USER="${INDIALLSKY_WEB_USER:-}"
WEB_PASS="${INDIALLSKY_WEB_PASS:-}"
WEB_NAME="${INDIALLSKY_WEB_NAME:-}"
WEB_EMAIL="${INDIALLSKY_WEB_EMAIL:-}"

OPTIONAL_PYTHON_MODULES="${INDIALLSKY_OPTIONAL_PYTHON_MODULES:-false}"
GPIO_PYTHON_MODULES="${INDIALLSKY_GPIO_PYTHON_MODULES:-false}"

PYINDI_2_0_4="git+https://github.com/indilib/pyindi-client.git@d8ad88f#egg=pyindi-client"
PYINDI_2_0_0="git+https://github.com/indilib/pyindi-client.git@674706f#egg=pyindi-client"
PYINDI_1_9_9="git+https://github.com/indilib/pyindi-client.git@ce808b7#egg=pyindi-client"
PYINDI_1_9_8="git+https://github.com/indilib/pyindi-client.git@ffd939b#egg=pyindi-client"

WEBSERVER="${INDIALLSKY_WEBSERVER:-apache}"
STELLARMATE="${INDIALLSKY_STELLARMATE:-false}"
ASTROBERRY="${INDIALLSKY_ASTROBERRY:-false}"

INSTALL_MOSQUITTO="${INDIALLSKY_INSTALL_MOSQUITTO:-}"
#### end config ####


function catch_error() {
    echo
    echo
    echo "###############"
    echo "###  ERROR  ###"
    echo "###############"
    echo
    echo "The setup script exited abnormally, please try to run again..."
    echo
    echo
    exit 1
}
trap catch_error ERR

function catch_sigint() {
    echo
    echo
    echo "###############"
    echo "###  ERROR  ###"
    echo "###############"
    echo
    echo "The setup script was interrupted, please run the script again to finish..."
    echo
    exit 1
}
trap catch_sigint SIGINT



HTDOCS_FILES="
    .htaccess
"

IMAGE_FOLDER_FILES="
    .htaccess
    darks/.htaccess
    export/.htaccess
"


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

# get primary group
PGRP=$(id -ng)


if which whiptail >/dev/null 2>&1; then
    ### whiptail might not be installed on first run
    WHIPTAIL_BIN=$(which whiptail)

    ### testing
    #WHIPTAIL_BIN=""
fi


echo "###############################################"
echo "### Welcome to the indi-allsky setup script ###"
echo "###############################################"


if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo
    echo "Please do not run $(basename "$0") with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
    echo
    echo
    exit 1
fi


ROOT_FREE=$(df -Pk / | tail -n 1 | awk "{ print \$4 }")
if [ "$ROOT_FREE" -lt 1000000 ]; then
    echo
    echo "Not enough free space available in / (root) filesystem"
    echo "At least 1GB of space needs to be available to continue"
    exit 1
fi


VAR_FREE=$(df -Pk /var | tail -n 1 | awk "{ print \$4 }")
if [ "$VAR_FREE" -lt 1000000 ]; then
    echo
    echo "Not enough free space available in /var filesystem"
    echo "At least 1GB of space needs to be available to continue"
    exit 1
fi


# basic checks
if ! [[ "$HTTP_PORT" =~ ^[^0][0-9]{1,5}$ ]]; then
    echo "Invalid HTTP port: $HTTP_PORT"
    echo
    exit 1
fi

if ! [[ "$HTTPS_PORT" =~ ^[^0][0-9]{1,5}$ ]]; then
    echo "Invalid HTTPS port: $HTTPS_PORT"
    echo
    exit 1
fi

if ! [[ "$INDI_PORT" =~ ^[^0][0-9]{1,5}$ ]]; then
    echo "Invalid INDI port: $INDI_PORT"
    echo
    exit 1
fi


if [ -f "/usr/local/bin/indiserver" ]; then
    # Do not install INDI
    INSTALL_INDI="false"
    INDI_DRIVER_PATH="/usr/local/bin"

    echo
    echo "Detected a custom installation of INDI in /usr/local/bin"
    echo
fi


if [[ "$CPU_ARCH" == "aarch64" && "$CPU_BITS" == "32" ]]; then
    echo
    echo
    echo "Detected 64-bit kernel (aarch64) on 32-bit system image"
    echo "You must add the following parameter to /boot/firmware/config.txt and reboot:"
    echo
    echo "  arm_64bit=0"
    echo
    exit 1
fi


if [[ -d "/etc/stellarmate" ]]; then
    echo
    echo
    echo "Detected Stellarmate"
    echo

    STELLARMATE="true"
    WEBSERVER="nginx"

    # Stellarmate already has services on 80
    if [ "$HTTP_PORT" -eq 80 ]; then
        HTTP_PORT="81"
        echo "Changing HTTP_PORT to 81"
    fi

    if [ "$HTTPS_PORT" -eq 443 ]; then
        HTTPS_PORT="444"
        echo "Changing HTTPS_PORT to 444"
    fi

    echo
    echo
    sleep 3

elif [[ -f "/etc/astroberry.version" ]]; then
    echo
    echo
    echo "Detected Astroberry server"
    echo

    if [ -n "${WHIPTAIL_BIN:-}" ]; then
        if ! "$WHIPTAIL_BIN" --title "WARNING" --yesno "Astroberry is no longer supported.  Please use Raspbian or Ubuntu.\n\nDo you want to proceed anyway?" 0 0 --defaultno; then
            exit 1
        fi
    else
        echo
        echo "!!! WARNING !!!  Astroberry is no longer supported.  Please use Raspbian or Ubuntu."
        echo
        sleep 10
    fi


    ASTROBERRY="true"
    WEBSERVER="nginx"


    # Astroberry already has services on 80/443
    if [ "$HTTP_PORT" -eq 80 ]; then
        HTTP_PORT="81"
        echo "Changing HTTP_PORT to 81"
    fi

    if [ "$HTTPS_PORT" -eq 443 ]; then
        HTTPS_PORT="444"
        echo "Changing HTTPS_PORT to 444"
    fi

    echo
    echo
    sleep 3
fi


if systemctl --user --quiet is-active "${ALLSKY_SERVICE_NAME}.service" >/dev/null 2>&1; then
    echo
    echo
    echo "ERROR: indi-allsky is running.  Please stop the service before running this script."
    echo
    echo "    systemctl --user stop ${ALLSKY_SERVICE_NAME}"
    echo
    exit 1
fi


if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


if systemctl --quiet is-enabled "nginx.service" 2>/dev/null; then
    if [ -e "/etc/nginx/sites-enabled/indi-allsky.conf" ]; then
        echo
        echo "Detected nginx web server is active"
        echo

        #sleep 3

        WEBSERVER="nginx"
    fi
fi


if [ -n "${WHIPTAIL_BIN:-}" ]; then
    "$WHIPTAIL_BIN" \
        --title "Welcome to indi-allsky" \
        --msgbox "*** Welcome to the indi-allsky setup script ***\n\nDistribution: $DISTRO_ID\nRelease: $DISTRO_VERSION_ID\nArch: $CPU_ARCH\nBits: $CPU_BITS\n\nCPUs: $CPU_TOTAL\nMemory: $MEM_TOTAL kB\n\nINDI Port: $INDI_PORT\n\nWeb Server: $WEBSERVER\nHTTP Port: $HTTP_PORT\nHTTPS Port: $HTTPS_PORT" 0 0
fi


echo
echo
echo "Distribution: $DISTRO_ID"
echo "Release: $DISTRO_VERSION_ID"
echo "Arch: $CPU_ARCH"
echo "Bits: $CPU_BITS"
echo
echo "CPUs: $CPU_TOTAL"
echo "Memory: $MEM_TOTAL kB"
echo
echo "INDI_DRIVER_PATH: $INDI_DRIVER_PATH"
echo "INDISERVER_SERVICE_NAME: $INDISERVER_SERVICE_NAME"
echo "ALLSKY_SERVICE_NAME: $ALLSKY_SERVICE_NAME"
echo "GUNICORN_SERVICE_NAME: $GUNICORN_SERVICE_NAME"
echo "UPGRADE_ALLSKY_SERVICE_NAME: $UPGRADE_ALLSKY_SERVICE_NAME"
echo "ALLSKY_ETC: $ALLSKY_ETC"
echo "HTDOCS_FOLDER: $HTDOCS_FOLDER"
echo "DB_FOLDER: $DB_FOLDER"
echo "DB_FILE: $DB_FILE"
echo "INSTALL_INDI: $INSTALL_INDI"
echo "INDI_PORT: $INDI_PORT"
echo "WEBSERVER: $WEBSERVER"
echo "HTTP_PORT: $HTTP_PORT"
echo "HTTPS_PORT: $HTTPS_PORT"
echo
echo


if ! ping -c 1 "$(hostname -s)" >/dev/null 2>&1; then
    echo "To avoid the benign warnings 'Name or service not known sudo: unable to resolve host'"
    echo "Add the following line to your /etc/hosts file:"
    echo "127.0.0.1       localhost $(hostname -s)"
    echo
    echo
fi

echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


START_TIME=$(date +%s)


if [ -n "${WHIPTAIL_BIN:-}" ]; then
    while [ -z "${CAMERA_INTERFACE:-}" ]; do
        # shellcheck disable=SC2068
        CAMERA_INTERFACE=$("$WHIPTAIL_BIN" \
            --title "Select camera interface" \
            --nocancel \
            --radiolist "indi-allsky supports the following camera interfaces.\n\nWiki:  https://github.com/aaronwmorris/indi-allsky/wiki/Camera-Interfaces\n\nPress space to select" 0 0 0 \
                "indi" "For astro/planetary cameras normally connected via USB (ZWO, QHY, PlayerOne, SVBony, Altair, Touptek, etc)" "OFF" \
                "libcamera" "Supports cameras connected via CSI interface on Raspberry Pi SBCs (Raspi HQ Camera, Camera Module 3, etc)" "OFF" \
                "mqtt_libcamera" "MQTT controlled remote libcamera CSI camera" "OFF" \
                "pycurl_camera" "Download images from a remote web camera" "OFF" \
                "indi_accumulator" "Create synthetic exposures using multiple sub-exposures" "OFF" \
                "indi_passive" "Connect a second instance of indi-allsky to an existing indi-allsky indiserver" "OFF" \
                "test_rotating_stars" "Rotating Stars Test Camera" "OFF" \
                "test_bubbles" "Bubbles Test Camera" "OFF" \
            3>&1 1>&2 2>&3)


        if [ "$CAMERA_INTERFACE" == "libcamera" ]; then
            # more specific libcamera selection

            while [ -z "${LIBCAMERA_INTERFACE:-}" ]; do
                LIBCAMERA_INTERFACE=$("$WHIPTAIL_BIN" \
                    --title "Select a libcamera interface: " \
                    --nocancel \
                    --notags \
                    --radiolist "https://github.com/aaronwmorris/indi-allsky/wiki/Camera-Interfaces\n\nPress space to select" 0 0 0 \
                        "libcamera_imx477" "IMX477 - Raspberry Pi HQ Camera" "OFF" \
                        "libcamera_imx378" "IMX378" "OFF" \
                        "libcamera_imx708" "IMX708 - Camera Module 3" "OFF" \
                        "libcamera_imx519" "IMX519" "OFF" \
                        "libcamera_imx500_ai" "IMX500 - AI Camera" "OFF" \
                        "libcamera_imx283" "IMX283 - Klarity/OneInchEye" "OFF" \
                        "libcamera_imx462" "IMX462" "OFF" \
                        "libcamera_imx327" "IMX327" "OFF" \
                        "libcamera_imx678" "IMX678 - Darksee" "OFF" \
                        "libcamera_imx335" "IMX335" "OFF" \
                        "libcamera_ov5647" "OV5647" "OFF" \
                        "libcamera_imx219" "IMX219 - Camera Module 2" "OFF" \
                        "libcamera_imx296_gs" "IMX296 - Global Shutter - Mono" "OFF" \
                        "libcamera_imx296_gs_color" "IMX296 - Global Shutter - Color" "OFF" \
                        "libcamera_imx290" "IMX290" "OFF" \
                        "libcamera_imx298" "IMX298" "OFF" \
                        "libcamera_64mp_hawkeye" "64MP Hawkeye (IMX682)" "OFF" \
                        "libcamera_64mp_owlsight" "64MP OwlSight (OV64A40)" "OFF" \
                        "restart" "Restart camera selection" "OFF" \
                    3>&1 1>&2 2>&3)
            done

            if [ "$LIBCAMERA_INTERFACE" == "restart" ]; then
                CAMERA_INTERFACE=""
                LIBCAMERA_INTERFACE=""
                continue
            fi

            CAMERA_INTERFACE="$LIBCAMERA_INTERFACE"

        elif [ "$CAMERA_INTERFACE" == "mqtt_libcamera" ]; then
            # more specific mqtt libcamera selection

            while [ -z "${MQTT_LIBCAMERA_INTERFACE:-}" ]; do
                MQTT_LIBCAMERA_INTERFACE=$("$WHIPTAIL_BIN" \
                    --title "Select a mqtt libcamera interface: " \
                    --nocancel \
                    --notags \
                    --radiolist "https://github.com/aaronwmorris/indi-allsky/wiki/Camera-Interfaces\n\nPress space to select" 0 0 0 \
                        "mqtt_imx477" "IMX477 - Raspberry Pi HQ Camera" "OFF" \
                        "mqtt_imx378" "IMX378" "OFF" \
                        "mqtt_imx708" "IMX708 - Camera Module 3" "OFF" \
                        "mqtt_64mp_owlsight" "64MP OwlSight (OV64A40)" "OFF" \
                        "restart" "Restart camera selection" "OFF" \
                    3>&1 1>&2 2>&3)
            done

            if [ "$MQTT_LIBCAMERA_INTERFACE" == "restart" ]; then
                CAMERA_INTERFACE=""
                MQTT_LIBCAMERA_INTERFACE=""
                continue
            fi

            CAMERA_INTERFACE="$MQTT_LIBCAMERA_INTERFACE"
        fi

    done
else
    while [ -z "${CAMERA_INTERFACE:-}" ]; do
        echo
        echo
        echo "indi-allsky supports the following camera interfaces."
        echo
        echo "Wiki:  https://github.com/aaronwmorris/indi-allsky/wiki/Camera-Interfaces"
        echo
        echo "                indi: For astro/planetary cameras normally connected via USB (ZWO, QHY, PlayerOne, SVBony, Altair, Touptek, etc)"
        echo "           libcamera: Supports cameras connected via CSI interface on Raspberry Pi SBCs (Raspi HQ Camera, Camera Module 3, etc)"
        echo "      mqtt_libcamera: MQTT controlled remote libcamera CSI camera"
        echo "       pycurl_camera: Download images from a remote web camera"
        echo "    indi_accumulator: Create synthetic exposures using multiple sub-exposures"
        echo "        indi_passive: Connect a second instance of indi-allsky to an existing indi-allsky indiserver"
        echo " test_rotating_stars: Rotating Stars Test Camera"
        echo "        test_bubbles: Bubbles Test Camera"
        echo

        PS3="Select a camera interface: "
        select camera_interface in indi libcamera mqtt_libcamera pycurl_camera indi_accumulator indi_passive test_rotating_stars test_bubbles; do
            if [ -n "$camera_interface" ]; then
                CAMERA_INTERFACE="$camera_interface"
                break
            fi
        done


        if [ "$CAMERA_INTERFACE" == "libcamera" ]; then
            # more specific libcamera selection
            INSTALL_LIBCAMERA="true"

            echo
            PS3="Select a libcamera interface: "
            select libcamera_interface in libcamera_imx477 libcamera_imx378 libcamera_imx708 libcamera_imx519 libcamera_imx500_ai libcamera_imx283 libcamera_imx462 libcamera_imx327 libcamera_imx678 libcamera_imx335 libcamera_ov5647 libcamera_imx219 libcamera_imx296_gs libcamera_imx296_gs_color libcamera_imx290 libcamera_imx298 libcamera_64mp_hawkeye libcamera_64mp_owlsight; do

                if [ -n "$libcamera_interface" ]; then
                    # overwrite variable
                    CAMERA_INTERFACE="$libcamera_interface"
                    break
                fi
            done

        elif [ "$CAMERA_INTERFACE" == "mqtt_libcamera" ]; then
            # more specific mqtt libcamera selection
            echo
            PS3="Select a mqtt libcamera interface: "
            select mqtt_libcamera_interface in mqtt_imx477 mqtt_imx378 mqtt_imx708 mqtt_64mp_owlsight; do

                if [ -n "$mqtt_libcamera_interface" ]; then
                    # overwrite variable
                    CAMERA_INTERFACE="$mqtt_libcamera_interface"
                    break
                fi
            done
        fi

    done
fi


echo
echo "Selected interface: $CAMERA_INTERFACE"
echo
sleep 3


if [[ -f "/usr/local/bin/libcamera-still" || -f "/usr/local/bin/rpicam-still" ]]; then
    INSTALL_LIBCAMERA="false"

    echo
    echo
    echo "Detected a custom installation of libcamera in /usr/local"
    echo
    echo
    sleep 3
fi


echo
echo
echo "Fixing git checkout permissions"
sudo find "$(dirname "$0")" ! -user "$USER" -exec chown "$USER" {} \;
sudo find "$(dirname "$0")" -type d ! -perm -555 -exec chmod ugo+rx {} \;
sudo find "$(dirname "$0")" -type f ! -perm -444 -exec chmod ugo+r {} \;



while [ -z "${OS_PACKAGE_UPGRADE:-}" ]; do
    if [ -n "${WHIPTAIL_BIN:-}" ]; then
        if "$WHIPTAIL_BIN" --title "Upgrade system packages" --yesno "Would you like to upgrade all of the system packages to the latest versions?" 0 0 --defaultno; then
            OS_PACKAGE_UPGRADE="true"
        else
            OS_PACKAGE_UPGRADE="false"
        fi
    else
        echo
        echo
        echo "Would you like to upgrade all of the system packages to the latest versions? "
        PS3="? "
        select package_upgrade in no yes ; do
            if [ "${package_upgrade:-}" == "yes" ]; then
                OS_PACKAGE_UPGRADE="true"
                break
            else
                OS_PACKAGE_UPGRADE="false"
                break
            fi
        done
    fi
done


if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "raspbian" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "13" ]]; then
        DISTRO="debian_13"
    elif [[ "$DISTRO_VERSION_ID" == "12" ]]; then
        DISTRO="debian_12"
    elif [[ "$DISTRO_VERSION_ID" == "11" ]]; then
        DISTRO="debian_11"
    elif [[ "$DISTRO_VERSION_ID" == "10" ]]; then
        DISTRO="debian_10"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "ubuntu" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "24.04" ]]; then
        DISTRO="ubuntu_24.04"
    elif [[ "$DISTRO_VERSION_ID" == "22.04" ]]; then
        DISTRO="ubuntu_22.04"
    elif [[ "$DISTRO_VERSION_ID" == "20.04" ]]; then
        DISTRO="ubuntu_20.04"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "linuxmint" ]]; then
    if [[ "$DISTRO_VERSION_ID" =~ ^22 ]]; then
        DISTRO="ubuntu_24.04"
    elif [[ "$DISTRO_VERSION_ID" =~ ^21 ]]; then
        DISTRO="ubuntu_22.04"
    elif [[ "$DISTRO_VERSION_ID" == "6" ]]; then
        DISTRO="debian_12"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


### These are the default requirements which may be overridden
VIRTUALENV_REQ=requirements/requirements_latest.txt
VIRTUALENV_REQ_OPT=requirements/requirements_optional.txt
VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
VIRTUALENV_REQ_GPIO=requirements/requirements_gpio.txt


echo "**** Installing packages... ****"
if [[ "$DISTRO" == "debian_13" ]]; then
    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.13


    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi


    INSTALL_INDI="false"

    if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
        echo
        echo
        echo "There are not prebuilt indi packages for this distribution"
        echo "Please run ./misc/build_indi.sh before running setup.sh"
        echo
        echo
        exit 1
    fi


    sudo apt-get update


    if [ "$OS_PACKAGE_UPGRADE" == "true" ]; then
        sudo apt-get -y dist-upgrade
    fi


    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        bc \
        procps \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        locales \
        ca-certificates \
        avahi-daemon \
        swig \
        libatlas-ecmwf-dev \
        libimath-dev \
        libopenexr-dev \
        libgtk-3-0t64 \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        libraw-dev \
        libgeos-dev \
        libtiff-dev \
        libjpeg62-turbo-dev \
        libopenjp2-7-dev \
        libpng-dev \
        zlib1g-dev \
        libfreetype-dev \
        liblcms2-dev \
        libwebp-dev \
        libcap-dev \
        tcl8.6-dev \
        tk8.6-dev \
        python3-tk \
        libharfbuzz-dev \
        libfribidi-dev \
        libxcb1-dev \
        default-libmysqlclient-dev \
        pkgconf \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        libgpiod3 \
        i2c-tools \
        network-manager \
        udisks2 \
        dnsmasq-base \
        polkitd \
        dbus-user-session


    # this can fail on non-raspberry pi OS repos
    sudo apt-get -y install \
        liblgpio-dev || true


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-sv305 \
            libsv305 \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx \
            indi-gpsd \
            indi-gpsnmea
    fi

    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        sudo apt-get -y install \
            rpicam-apps
    fi

elif [[ "$DISTRO" == "debian_12" ]]; then
    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.11


    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi


    INSTALL_INDI="false"

    if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
        echo
        echo
        echo "There are not prebuilt indi packages for this distribution"
        echo "Please run ./misc/build_indi.sh before running setup.sh"
        echo
        echo
        exit 1
    fi


    sudo apt-get update


    if [ "$OS_PACKAGE_UPGRADE" == "true" ]; then
        sudo apt-get -y dist-upgrade
    fi


    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        bc \
        procps \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        locales \
        ca-certificates \
        avahi-daemon \
        swig \
        libatlas-base-dev \
        libimath-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        libraw-dev \
        libgeos-dev \
        libtiff-dev \
        libjpeg62-turbo-dev \
        libopenjp2-7-dev \
        libpng-dev \
        zlib1g-dev \
        libfreetype-dev \
        liblcms2-dev \
        libwebp-dev \
        libcap-dev \
        tcl8.6-dev \
        tk8.6-dev \
        python3-tk \
        libharfbuzz-dev \
        libfribidi-dev \
        libxcb1-dev \
        default-libmysqlclient-dev \
        pkgconf \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        libgpiod2 \
        i2c-tools \
        network-manager \
        udisks2 \
        dnsmasq-base \
        polkitd \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-sv305 \
            libsv305 \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx \
            indi-gpsd \
            indi-gpsnmea
    fi

    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        sudo apt-get -y install \
            rpicam-apps
    fi

elif [[ "$DISTRO" == "debian_11" ]]; then
    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.9


    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
    else
        VIRTUALENV_REQ=requirements/requirements_debian11.txt
    fi


    INSTALL_INDI="false"

    if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
        echo
        echo
        echo "There are not prebuilt indi packages for this distribution"
        echo "Please run ./misc/build_indi.sh before running setup.sh"
        echo
        echo
        exit 1
    fi


    sudo apt-get update


    if [ "$OS_PACKAGE_UPGRADE" == "true" ]; then
        sudo apt-get -y dist-upgrade
    fi


    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        bc \
        procps \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        locales \
        ca-certificates \
        avahi-daemon \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        libraw-dev \
        libgeos-dev \
        libtiff5-dev \
        libjpeg62-turbo-dev \
        libopenjp2-7-dev \
        libpng-dev \
        zlib1g-dev \
        libfreetype6-dev \
        liblcms2-dev \
        libwebp-dev \
        libcap-dev \
        tcl8.6-dev \
        tk8.6-dev \
        python3-tk \
        libharfbuzz-dev \
        libfribidi-dev \
        libxcb1-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        libgpiod2 \
        i2c-tools \
        network-manager \
        udisks2 \
        dnsmasq-base \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-sv305 \
            libsv305 \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx \
            indi-gpsd \
            indi-gpsnmea
    fi


    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        # this can fail on non-raspberry pi OS repos
        sudo apt-get -y install \
            libcamera-apps || true
    fi

elif [[ "$DISTRO" == "debian_10" ]]; then
    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.7

    VIRTUALENV_REQ=requirements/requirements_debian10.txt
    VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt


    if [[ "$CAMERA_INTERFACE" =~ ^libcamera ]]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    INSTALL_INDI="false"

    if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
        echo
        echo
        echo "There are not prebuilt indi packages for this distribution"
        echo "Please run ./misc/build_indi.sh before running setup.sh"
        echo
        echo
        exit 1
    fi


    sudo apt-get update


    if [ "$OS_PACKAGE_UPGRADE" == "true" ]; then
        sudo apt-get -y dist-upgrade
    fi


    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        bc \
        procps \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        locales \
        ca-certificates \
        avahi-daemon \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        libraw-dev \
        libgeos-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        libgpiod2 \
        i2c-tools \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-rpicam \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-sv305 \
            libsv305 \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx \
            indi-gpsd \
            indi-gpsnmea
    fi
elif [[ "$DISTRO" == "ubuntu_24.04" ]]; then
    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.12


    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi


    if [[ "$CPU_ARCH" == "x86_64" && "$CPU_BITS" == "64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository -y ppa:mutlaqja/ppa
        fi
    elif [[ "$CPU_ARCH" == "aarch64" && "$CPU_BITS" == "64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository -y ppa:mutlaqja/ppa
        fi
    else
        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi
    fi


    sudo apt-get update


    if [ "$OS_PACKAGE_UPGRADE" == "true" ]; then
        sudo apt-get -y dist-upgrade
    fi


    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        bc \
        procps \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        locales \
        ca-certificates \
        avahi-daemon \
        swig \
        libatlas-base-dev \
        libimath-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        libraw-dev \
        libgeos-dev \
        libtiff-dev \
        libjpeg8-dev \
        libopenjp2-7-dev \
        libpng-dev \
        zlib1g-dev \
        libfreetype-dev \
        liblcms2-dev \
        libwebp-dev \
        libcap-dev \
        tcl8.6-dev \
        tk8.6-dev \
        python3-tk \
        libharfbuzz-dev \
        libfribidi-dev \
        libxcb1-dev \
        default-libmysqlclient-dev \
        pkgconf \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        libgpiod2 \
        i2c-tools \
        network-manager \
        udisks2 \
        dnsmasq-base \
        polkitd \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-svbony \
            libsvbony \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx \
            indi-gpsd \
            indi-gpsnmea
    fi


    #if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
    #    sudo apt-get -y install \
    #        rpicam-apps
    #fi


elif [[ "$DISTRO" == "ubuntu_22.04" ]]; then
    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.11


    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi


    if [[ "$CPU_ARCH" == "x86_64" && "$CPU_BITS" == "64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository -y ppa:mutlaqja/ppa
        fi
    elif [[ "$CPU_ARCH" == "aarch64" && "$CPU_BITS" == "64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository -y ppa:mutlaqja/ppa
        fi
    else
        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi
    fi


    sudo apt-get update


    if [ "$OS_PACKAGE_UPGRADE" == "true" ]; then
        sudo apt-get -y dist-upgrade
    fi


    sudo apt-get -y install \
        build-essential \
        python3.11 \
        python3.11-dev \
        python3.11-venv \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        bc \
        procps \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        locales \
        ca-certificates \
        avahi-daemon \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        libraw-dev \
        libgeos-dev \
        libtiff5-dev \
        libjpeg8-dev \
        libopenjp2-7-dev \
        libpng-dev \
        zlib1g-dev \
        libfreetype6-dev \
        liblcms2-dev \
        libwebp-dev \
        libcap-dev \
        tcl8.6-dev \
        tk8.6-dev \
        python3-tk \
        libharfbuzz-dev \
        libfribidi-dev \
        libxcb1-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        libgpiod2 \
        i2c-tools \
        network-manager \
        udisks2 \
        dnsmasq-base \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-svbony \
            libsvbony \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx \
            indi-gpsd \
            indi-gpsnmea
    fi

elif [[ "$DISTRO" == "ubuntu_20.04" ]]; then
    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm

    MYSQL_ETC="/etc/mysql"

    PYTHON_BIN=python3.9


    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
    else
        VIRTUALENV_REQ=requirements/requirements_debian11.txt
    fi


    if [[ "$CPU_ARCH" == "x86_64" && "$CPU_BITS" == "64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository -y ppa:mutlaqja/ppa
        fi
    elif [[ "$CPU_ARCH" == "aarch64" && "$CPU_BITS" == "64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository -y ppa:mutlaqja/ppa
        fi
    else
        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi
    fi


    sudo apt-get update


    if [ "$OS_PACKAGE_UPGRADE" == "true" ]; then
        sudo apt-get -y dist-upgrade
    fi


    sudo apt-get -y install \
        build-essential \
        python3.9 \
        python3.9-dev \
        python3.9-venv \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        bc \
        procps \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        locales \
        ca-certificates \
        avahi-daemon \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libgnutls28-dev \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        libraw-dev \
        libgeos-dev \
        libtiff5-dev \
        libjpeg8-dev \
        libopenjp2-7-dev \
        libpng-dev \
        zlib1g-dev \
        libfreetype6-dev \
        liblcms2-dev \
        libwebp-dev \
        libcap-dev \
        tcl8.6-dev \
        tk8.6-dev \
        python3-tk \
        libharfbuzz-dev \
        libfribidi-dev \
        libxcb1-dev \
        default-libmysqlclient-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        libgpiod2 \
        i2c-tools \
        network-manager \
        udisks2 \
        policykit-1 \
        dbus-user-session


    if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
        sudo apt-get -y install \
            mariadb-server
    fi


    if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
        if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
            INSTALL_INDI="false"
        fi
    fi

    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
            indi-webcam \
            indi-asi \
            libasi \
            indi-qhy \
            libqhy \
            indi-playerone \
            libplayerone \
            indi-svbony \
            libsvbony \
            libaltaircam \
            libmallincam \
            libmicam \
            libnncam \
            indi-toupbase \
            libtoupcam \
            indi-gphoto \
            indi-sx \
            indi-gpsd \
            indi-gpsnmea
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


if [[ "$STELLARMATE" == "true" ]]; then
    # nginx already installed
    #sudo apt-get -y install \
    #    nginx

    # stellarmate does not install libindi-dev by default
    if ! dpkg -s libindi-dev >/dev/null; then
        sudo apt-get -y install \
            libindi-dev
    fi
elif [[ "$ASTROBERRY" == "true" ]]; then
    # nginx already installed
    :
else
    if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "ubuntu" || "$DISTRO_ID" == "raspbian" || "$DISTRO_ID" == "linuxmint" ]]; then
        if [ "$WEBSERVER" == "nginx" ]; then
            sudo apt-get -y install \
                nginx
        elif [ "$WEBSERVER" == "apache" ]; then
            sudo apt-get -y install \
                apache2
        else
            echo
            echo "Unknown webserver: $WEBSERVER"
            echo

            exit 1
        fi
    fi
fi


if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    #sudo systemctl start "user@${UID}.service"
    #export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${UID}/bus"

    echo
    echo
    echo "The DBUS user session is not defined"
    echo
    echo "Now that the dbus package has been installed..."
    echo "Please reboot your system and re-run this script to continue"
    echo
    echo "WARNING: If you use screen, tmux, or byobu for virtual sessions, this check may always fail"
    echo
    exit 1
fi


if systemctl --quiet is-enabled "${INDISERVER_SERVICE_NAME}" 2>/dev/null; then
    # system
    INSTALL_INDISERVER="false"
elif systemctl --user --quiet is-enabled "${INDISERVER_SERVICE_NAME}.timer" 2>/dev/null; then
    while [ -z "${INSTALL_INDISERVER:-}" ]; do
        # user
        if whiptail --title "indiserver update" --yesno "An indiserver service is already defined, would you like to replace it?\n\nThis is normally not needed during an upgrade.\n\nIf you are trying change camera vendors, choose YES" 0 0 --defaultno; then
            INSTALL_INDISERVER="true"
        else
            INSTALL_INDISERVER="false"
        fi
    done
else
    INSTALL_INDISERVER="true"
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR" || catch_error
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD" || catch_error


echo "**** Ensure path to git folder is traversable ****"
# Web servers running as www-data or nobody need to be able to read files in the git checkout
PARENT_DIR="$ALLSKY_DIRECTORY"
while true; do
    if [ "$PARENT_DIR" == "/" ]; then
        break
    elif [ "$PARENT_DIR" == "." ]; then
        break
    fi

    echo "Setting other execute bit on $PARENT_DIR"
    sudo chmod ugo+x "$PARENT_DIR"

    PARENT_DIR=$(dirname "$PARENT_DIR")
done


TMP_SPACE=$(df -Pk /tmp | tail -n 1 | awk "{ print \$4 }")
if [ "$TMP_SPACE" -lt 500000 ]; then
    whiptail --msgbox "There is less than 512MB available in the /tmp filesystem\n\nThis *MAY* cause python module installations to fail on new installs" 0 0 --title "WARNING"
fi


echo "**** Python virtualenv setup ****"
[[ ! -d "${ALLSKY_DIRECTORY}/virtualenv" ]] && mkdir "${ALLSKY_DIRECTORY}/virtualenv"
chmod 775 "${ALLSKY_DIRECTORY}/virtualenv"
if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky" ]; then
    "${PYTHON_BIN}" -m venv "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky"
fi


if whiptail --title "Optional Python Modules" --yesno "Would you like to install optional python modules? (Additional database, object storage, YouTube support)" 0 0 --defaultno; then
    OPTIONAL_PYTHON_MODULES=true
fi

if whiptail --title "GPIO Python Modules" --yesno "Would you like to install GPIO python modules? (Hardware device support)" 0 0 --defaultno; then
    GPIO_PYTHON_MODULES=true
fi


# shellcheck source=/dev/null
source "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate"

pip3 install --upgrade pip setuptools wheel packaging


PIP_REQ_ARGS=("-r" "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ}")

if [ "${OPTIONAL_PYTHON_MODULES}" == "true" ]; then
    PIP_REQ_ARGS+=("-r" "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ_OPT}")
fi

if [ "${GPIO_PYTHON_MODULES}" == "true" ]; then
    PIP_REQ_ARGS+=("-r" "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ_GPIO}")
fi

pip3 install "${PIP_REQ_ARGS[@]}"


# some modules do not have their prerequisites set
pip3 install -r "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ_POST}"


# replace rpi.gpio module with rpi.lgpio in some cases
if [ "${GPIO_PYTHON_MODULES}" == "true" ]; then
    if [[ "$DISTRO" == "debian_13" || "$DISTRO" == "debian_12" || "$DISTRO" == "ubuntu_24.04" ]]; then
        if [[ "$CPU_ARCH" == "aarch64" || "$CPU_ARCH" == "armv7l" ]]; then
            pip3 uninstall -y RPi.GPIO rpi.lgpio

            pip3 install rpi.lgpio
        fi
    fi
fi


# pyindi-client setup
SUPPORTED_INDI_VERSIONS=(
    "2.1.8"
    "2.1.7"
    "2.1.6"
    "2.1.5"
    "2.1.4"
    "2.1.3"
    "2.1.2.1"
    "2.1.2"
    "2.1.1"
    "2.1.0"
    "2.0.9"
    "2.0.8"
    "2.0.7"
    "2.0.6"
    "2.0.5"
    "2.0.4"
    "2.0.3"
    "2.0.2"
    "2.0.1"
    "2.0.0"
    "1.9.9"
    "1.9.8"
    "1.9.7"
    "skip"
)


# try to detect installed indiversion
if pkg-config --modversion libindi >/dev/null 2>&1; then
    #DETECTED_INDIVERSION=$(${INDI_DRIVER_PATH}/indiserver --help 2>&1 | grep -i "INDI Library" | awk "{print \$3}")
    DETECTED_INDIVERSION=$(pkg-config --modversion libindi)
else
    echo
    echo
    echo "The libindi development packages cannot be found.  Please install libindi-dev"
    echo
    exit 1
fi


echo
echo
echo "Detected INDI version: $DETECTED_INDIVERSION"
sleep 3


if [ "$DETECTED_INDIVERSION" == "2.0.4" ]; then
    whiptail --msgbox "There is a bug in INDI 2.0.4 that will cause the build for pyindi-client to fail.\nThe following URL documents the needed fix.\n\nhttps://github.com/aaronwmorris/indi-allsky/wiki/INDI-2.0.4-bug" 0 0 --title "WARNING"
fi


INDI_VERSIONS=()
for v in "${SUPPORTED_INDI_VERSIONS[@]}"; do
    if [ "$v" == "$DETECTED_INDIVERSION" ]; then
        #INDI_VERSIONS[${#INDI_VERSIONS[@]}]="$v $v ON"

        INDI_VERSION=$v
        break
    else
        INDI_VERSIONS[${#INDI_VERSIONS[@]}]="$v $v OFF"
    fi
done



while [ -z "${INDI_VERSION:-}" ]; do
    # shellcheck disable=SC2068
    INDI_VERSION=$(whiptail --title "Installed INDI Version for pyindi-client" --nocancel --notags --radiolist "Press space to select" 0 0 0 ${INDI_VERSIONS[@]} 3>&1 1>&2 2>&3)
done

#echo "Selected: $INDI_VERSION"



if [ "$INDI_VERSION" == "2.0.3" ]; then
    pip3 install "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.2" ]; then
    pip3 install "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.1" ]; then
    pip3 install "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.0" ]; then
    pip3 install "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "1.9.9" ]; then
    pip3 install "$PYINDI_1_9_9"
elif [ "$INDI_VERSION" == "1.9.8" ]; then
    pip3 install "$PYINDI_1_9_8"
elif [ "$INDI_VERSION" == "1.9.7" ]; then
    pip3 install "$PYINDI_1_9_8"
else
    # default to latest release
    pip3 install "$PYINDI_2_0_4"
fi


### Camera ###

# Need this list so drivers are listed in specific order
INDI_CCD_DRIVER_ORDER=("indi_simulator_ccd" "indi_asi_ccd" "indi_asi_single_ccd" "indi_playerone_ccd" "indi_playerone_single_ccd" "indi_toupcam_ccd" "indi_altaircam_ccd" "indi_altair_ccd" "indi_omegonprocam_ccd" "indi_ogmacam_ccd" "indi_tscam_ccd" "indi_nncam_ccd" "indi_svbony_ccd" "indi_svbonycam_ccd" "indi_qhy_ccd" "indi_sx_ccd" "indi_dsi_ccd" "indi_libcamera_ccd" "indi_gphoto_ccd" "indi_canon_ccd" "indi_sony_ccd" "indi_nikon_ccd" "indi_fuji_ccd" "indi_pentax_ccd" "indi_v4l2_ccd" "indi_webcam_ccd")

declare -A INDI_CCD_DRIVER_MAP
INDI_CCD_DRIVER_MAP[indi_simulator_ccd]="CCD Simulator"
INDI_CCD_DRIVER_MAP[indi_asi_ccd]="ZWO ASI"
INDI_CCD_DRIVER_MAP[indi_asi_single_ccd]="ZWO ASI (Single)"
INDI_CCD_DRIVER_MAP[indi_playerone_ccd]="PlayerOne Astronomy"
INDI_CCD_DRIVER_MAP[indi_playerone_single_ccd]="PlayerOne Astronomy (Single)"
INDI_CCD_DRIVER_MAP[indi_toupcam_ccd]="ToupTek"
INDI_CCD_DRIVER_MAP[indi_altaircam_ccd]="Altair Astro (new)"
INDI_CCD_DRIVER_MAP[indi_altair_ccd]="Altair Astro (old)"
INDI_CCD_DRIVER_MAP[indi_omegonprocam_ccd]="Omegon"
INDI_CCD_DRIVER_MAP[indi_ogmacam_ccd]="Ogma"
INDI_CCD_DRIVER_MAP[indi_tscam_ccd]="indi_tscam_ccd"
INDI_CCD_DRIVER_MAP[indi_nncam_ccd]="indi_nncam_ccd"
INDI_CCD_DRIVER_MAP[indi_svbony_ccd]="SVBony"
INDI_CCD_DRIVER_MAP[indi_svbonycam_ccd]="SVBony"
INDI_CCD_DRIVER_MAP[indi_qhy_ccd]="QHY CCD"
INDI_CCD_DRIVER_MAP[indi_sx_ccd]="Starlight Xpress"
INDI_CCD_DRIVER_MAP[indi_dsi_ccd]="Meade DSI"
INDI_CCD_DRIVER_MAP[indi_libcamera_ccd]="libcamera (BETA)"
INDI_CCD_DRIVER_MAP[indi_gphoto_ccd]="GPhoto DSLR"
INDI_CCD_DRIVER_MAP[indi_canon_ccd]="Canon DSLR"
INDI_CCD_DRIVER_MAP[indi_sony_ccd]="Sony DSLR"
INDI_CCD_DRIVER_MAP[indi_nikon_ccd]="Nikon DSLR"
INDI_CCD_DRIVER_MAP[indi_fuji_ccd]="Fuji DSLR"
INDI_CCD_DRIVER_MAP[indi_pentax_ccd]="Pentax DSLR"
INDI_CCD_DRIVER_MAP[indi_v4l2_ccd]="Linux V4L2"
INDI_CCD_DRIVER_MAP[indi_webcam_ccd]="Web Camera"


INDI_CCD_DRIVERS=()
for item in "${INDI_CCD_DRIVER_ORDER[@]}"; do
    if [ -f "$INDI_DRIVER_PATH/$item" ]; then
        INDI_CCD_DRIVERS[${#INDI_CCD_DRIVERS[@]}]="$item"
        INDI_CCD_DRIVERS[${#INDI_CCD_DRIVERS[@]}]="${INDI_CCD_DRIVER_MAP[$item]}"
        INDI_CCD_DRIVERS[${#INDI_CCD_DRIVERS[@]}]="OFF"
    fi
done

#echo ${INDI_CCD_DRIVERS[@]}


if [[ "$INSTALL_INDISERVER" == "true" ]]; then
    if [[ "$CAMERA_INTERFACE" == "indi" || "$CAMERA_INTERFACE" == "indi_accumulator" ]]; then
        while [ -z "${CCD_DRIVER:-}" ]; do
            # shellcheck disable=SC2068
            CCD_DRIVER=$(whiptail --title "Camera Driver" --nocancel --radiolist "Press space to select" 0 0 0 "${INDI_CCD_DRIVERS[@]}" 3>&1 1>&2 2>&3)
        done
    else
        # simulator will not affect anything
        CCD_DRIVER=indi_simulator_ccd
    fi
fi

#echo $CCD_DRIVER


### GPS ###
INDI_GPS_DRIVER_ORDER=("indi_gpsd" "indi_gpsnmea" "indi_simulator_gps")

declare -A INDI_GPS_DRIVER_MAP
INDI_GPS_DRIVER_MAP[indi_gpsd]="GPSd"
INDI_GPS_DRIVER_MAP[indi_gpsnmea]="GPSd NMEA"
INDI_GPS_DRIVER_MAP[indi_simulator_gps]="GPS Simulator"


INDI_GPS_DRIVERS=("None" "None" "ON")
for item in "${INDI_GPS_DRIVER_ORDER[@]}"; do
    if [ -f "$INDI_DRIVER_PATH/$item" ]; then
        INDI_GPS_DRIVERS[${#INDI_GPS_DRIVERS[@]}]="$item"
        INDI_GPS_DRIVERS[${#INDI_GPS_DRIVERS[@]}]="${INDI_GPS_DRIVER_MAP[$item]}"
        INDI_GPS_DRIVERS[${#INDI_GPS_DRIVERS[@]}]="OFF"
    fi
done

#echo ${INDI_GPS_DRIVERS[@]}


if [[ "$INSTALL_INDISERVER" == "true" ]]; then
    while [ -z "${GPS_DRIVER:-}" ]; do
        # shellcheck disable=SC2068
        GPS_DRIVER=$(whiptail --title "GPS Driver" --nocancel --radiolist "Press space to select" 0 0 0 "${INDI_GPS_DRIVERS[@]}" 3>&1 1>&2 2>&3)
    done
fi

#echo $GPS_DRIVER

if [ "$GPS_DRIVER" == "None" ]; then
    # Value needs to be empty for None
    GPS_DRIVER=""
fi



# create users systemd folder
[[ ! -d "${HOME}/.config/systemd/user" ]] && mkdir -p "${HOME}/.config/systemd/user"


if [ "$INSTALL_INDISERVER" == "true" ]; then
    echo
    echo
    echo "**** Setting up indiserver service ****"


    # timer
    cp -f "${ALLSKY_DIRECTORY}/service/${INDISERVER_SERVICE_NAME}.timer" "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.timer"
    chmod 644 "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.timer"


    TMP1=$(mktemp)
    sed \
     -e "s|%INDI_DRIVER_PATH%|$INDI_DRIVER_PATH|g" \
     -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
     -e "s|%INDISERVER_USER%|$USER|g" \
     -e "s|%INDI_PORT%|$INDI_PORT|g" \
     -e "s|%INDI_CCD_DRIVER%|$CCD_DRIVER|g" \
     -e "s|%INDI_GPS_DRIVER%|$GPS_DRIVER|g" \
     "${ALLSKY_DIRECTORY}/service/indiserver.service" > "$TMP1"


    cp -f "$TMP1" "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.service"
    chmod 644 "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.service"
    [[ -f "$TMP1" ]] && rm -f "$TMP1"
else
    echo
    echo
    echo
    echo "! Bypassing indiserver setup"
fi


echo "**** Setting up indi-allsky service ****"
# timer
cp -f "${ALLSKY_DIRECTORY}/service/${ALLSKY_SERVICE_NAME}.timer" "${HOME}/.config/systemd/user/${ALLSKY_SERVICE_NAME}.timer"
chmod 644 "${HOME}/.config/systemd/user/${ALLSKY_SERVICE_NAME}.timer"


TMP2=$(mktemp)
sed \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 "${ALLSKY_DIRECTORY}/service/indi-allsky.service" > "$TMP2"

cp -f "$TMP2" "${HOME}/.config/systemd/user/${ALLSKY_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${ALLSKY_SERVICE_NAME}.service"
[[ -f "$TMP2" ]] && rm -f "$TMP2"


echo "**** Setting up gunicorn service ****"
TMP5=$(mktemp)
sed \
 -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 "${ALLSKY_DIRECTORY}/service/gunicorn-indi-allsky.socket" > "$TMP5"

cp -f "$TMP5" "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.socket"
chmod 644 "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.socket"
[[ -f "$TMP5" ]] && rm -f "$TMP5"

TMP6=$(mktemp)
sed \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 "${ALLSKY_DIRECTORY}/service/gunicorn-indi-allsky.service" > "$TMP6"

cp -f "$TMP6" "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.service"
[[ -f "$TMP6" ]] && rm -f "$TMP6"


echo "**** Setting up upgrade-indi-allsky service ****"
TMP_UPGRADE=$(mktemp)
sed \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 "${ALLSKY_DIRECTORY}/service/upgrade-indi-allsky.service" > "$TMP_UPGRADE"

cp -f "$TMP_UPGRADE" "${HOME}/.config/systemd/user/${UPGRADE_ALLSKY_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${UPGRADE_ALLSKY_SERVICE_NAME}.service"
[[ -f "$TMP_UPGRADE" ]] && rm -f "$TMP_UPGRADE"


echo "**** Enabling services ****"
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload

# indi-allsky service is started by the timer (2 minutes after boot)
systemctl --user disable "${ALLSKY_SERVICE_NAME}.service"

# gunicorn service is started by the socket
systemctl --user disable "${GUNICORN_SERVICE_NAME}.service"
systemctl --user enable "${GUNICORN_SERVICE_NAME}.socket"

# upgrade service is disabled by default
systemctl --user disable "${UPGRADE_ALLSKY_SERVICE_NAME}.service"


echo "**** Setup sudoers ****"
TMP_SUDOERS=$(mktemp)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 "${ALLSKY_DIRECTORY}/service/sudoers_indi-allsky" > "$TMP_SUDOERS"

sudo cp -f "$TMP_SUDOERS" "/etc/sudoers.d/indi-allsky"
sudo chown root:root "/etc/sudoers.d/indi-allsky"
sudo chmod 440 "/etc/sudoers.d/indi-allsky"
[[ -f "$TMP_SUDOERS" ]] && rm -f "$TMP_SUDOERS"


echo "**** Setup policy kit permissions ****"
TMP_POLKIT=$(mktemp)

if [ -d "/etc/polkit-1/rules.d" ]; then
    sed \
     -e "s|%ALLSKY_USER%|$USER|g" \
     "${ALLSKY_DIRECTORY}/service/90-indi-allsky.rules" > "$TMP_POLKIT"

    sudo cp -f "$TMP_POLKIT" "/etc/polkit-1/rules.d/90-indi-allsky.rules"
    sudo chown root:root "/etc/polkit-1/rules.d/90-indi-allsky.rules"
    sudo chmod 644 "/etc/polkit-1/rules.d/90-indi-allsky.rules"

    # remove legacy config
    if sudo test -f "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"; then
        sudo rm -f "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
    fi
else
    # legacy pkla
    sed \
     -e "s|%ALLSKY_USER%|$USER|g" \
     "${ALLSKY_DIRECTORY}/service/90-org.aaronwmorris.indi-allsky.pkla" > "$TMP_POLKIT"

    sudo cp -f "$TMP_POLKIT" "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
    sudo chown root:root "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
    sudo chmod 644 "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
fi

[[ -f "$TMP_POLKIT" ]] && rm -f "$TMP_POLKIT"


### alter network manager policy file
if sudo test -f "/var/lib/polkit-1/localauthority/10-vendor.d/org.freedesktop.NetworkManager.pkla"; then
    TMP_NM_PKLA=$(mktemp)
    sudo cat "/var/lib/polkit-1/localauthority/10-vendor.d/org.freedesktop.NetworkManager.pkla" | sed \
     -e 's|^ResultAny\=no$|ResultAny\=yes|i' > "$TMP_NM_PKLA"

    sudo cp -f "$TMP_NM_PKLA" /var/lib/polkit-1/localauthority/10-vendor.d/org.freedesktop.NetworkManager.pkla
    sudo chown root:root /var/lib/polkit-1/localauthority/10-vendor.d/org.freedesktop.NetworkManager.pkla
    sudo chmod 644 /var/lib/polkit-1/localauthority/10-vendor.d/org.freedesktop.NetworkManager.pkla
    [[ -f "$TMP_NM_PKLA" ]] && rm -f "$TMP_NM_PKLA"
fi


sudo systemctl restart polkit


echo "**** Ensure user is a member of the systemd-journal group ****"
sudo usermod -a -G systemd-journal "$USER"


echo "**** Setup rsyslog logging ****"
[[ ! -d "/var/log/indi-allsky" ]] && sudo mkdir /var/log/indi-allsky
sudo chmod 755 /var/log/indi-allsky
sudo touch /var/log/indi-allsky/indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/indi-allsky.log
sudo touch /var/log/indi-allsky/webapp-indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/webapp-indi-allsky.log
sudo chown -R "$RSYSLOG_USER":"$RSYSLOG_GROUP" /var/log/indi-allsky


# 10 prefix so they are process before the defaults in 50
sudo cp -f "${ALLSKY_DIRECTORY}/log/rsyslog_indi-allsky.conf" /etc/rsyslog.d/10-indi-allsky.conf
sudo chown root:root /etc/rsyslog.d/10-indi-allsky.conf
sudo chmod 644 /etc/rsyslog.d/10-indi-allsky.conf

# remove old version
[[ -f "/etc/rsyslog.d/indi-allsky.conf" ]] && sudo rm -f /etc/rsyslog.d/indi-allsky.conf

sudo systemctl restart rsyslog


sudo cp -f "${ALLSKY_DIRECTORY}/log/logrotate_indi-allsky" /etc/logrotate.d/indi-allsky
sudo chown root:root /etc/logrotate.d/indi-allsky
sudo chmod 644 /etc/logrotate.d/indi-allsky


echo "**** Indi-allsky config ****"
[[ ! -d "$ALLSKY_ETC" ]] && sudo mkdir "$ALLSKY_ETC"
sudo chown -R "$USER":"$PGRP" "$ALLSKY_ETC"
sudo chmod 775 "${ALLSKY_ETC}"


if [ ! -e "${ALLSKY_ETC}/indi-allsky.env" ]; then
    cp "${ALLSKY_DIRECTORY}/service/indi-allsky.env" "${ALLSKY_ETC}/indi-allsky.env"
fi

chmod 600 "${ALLSKY_ETC}/indi-allsky.env"


echo "**** Flask config ****"

while [ -z "${FLASK_AUTH_ALL_VIEWS:-}" ]; do
    if whiptail --title "Web Authentication" --yesno "Do you want to require authentication for all web site views?\n\nIf \"no\", privileged actions are still protected by authentication.\n\n(Hint: Most people should pick \"no\")" 0 0 --defaultno; then
        FLASK_AUTH_ALL_VIEWS="true"
    else
        FLASK_AUTH_ALL_VIEWS="false"
    fi
done


TMP_FLASK=$(mktemp --suffix=.json)
TMP_FLASK_MERGE=$(mktemp --suffix=.json)


jq \
 --arg sqlalchemy_database_uri "$SQLALCHEMY_DATABASE_URI" \
 --arg indi_allsky_docroot "$HTDOCS_FOLDER" \
 --argjson indi_allsky_auth_all_views "$FLASK_AUTH_ALL_VIEWS" \
 --arg migration_folder "$MIGRATION_FOLDER" \
 --arg allsky_service_name "${ALLSKY_SERVICE_NAME}.service" \
 --arg allsky_timer_name "${ALLSKY_SERVICE_NAME}.timer" \
 --arg indiserver_service_name "${INDISERVER_SERVICE_NAME}.service" \
 --arg indiserver_timer_name "${INDISERVER_SERVICE_NAME}.timer" \
 --arg gunicorn_service_name "${GUNICORN_SERVICE_NAME}.service" \
 '.SQLALCHEMY_DATABASE_URI = $sqlalchemy_database_uri | .INDI_ALLSKY_DOCROOT = $indi_allsky_docroot | .INDI_ALLSKY_AUTH_ALL_VIEWS = $indi_allsky_auth_all_views | .MIGRATION_FOLDER = $migration_folder | .ALLSKY_SERVICE_NAME = $allsky_service_name | .ALLSKY_TIMER_NAME = $allsky_timer_name | .INDISERVER_SERVICE_NAME = $indiserver_service_name | .INDISERVER_TIMER_NAME = $indiserver_timer_name | .GUNICORN_SERVICE_NAME = $gunicorn_service_name' \
 "${ALLSKY_DIRECTORY}/flask.json_template" > "$TMP_FLASK"


if [[ -f "${ALLSKY_ETC}/flask.json" ]]; then
    # make a backup
    cp -f "${ALLSKY_ETC}/flask.json" "${ALLSKY_ETC}/flask.json_old"
    chmod 640 "${ALLSKY_ETC}/flask.json_old"

    # attempt to merge configs giving preference to the original config (listed 2nd)
    jq -s '.[0] * .[1]' "$TMP_FLASK" "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_MERGE"
    cp -f "$TMP_FLASK_MERGE" "${ALLSKY_ETC}/flask.json"
else
    # new config
    cp -f "$TMP_FLASK" "${ALLSKY_ETC}/flask.json"
fi


INDIALLSKY_FLASK_SECRET_KEY=$(jq -r '.SECRET_KEY' "${ALLSKY_ETC}/flask.json")
if [[ -z "$INDIALLSKY_FLASK_SECRET_KEY" || "$INDIALLSKY_FLASK_SECRET_KEY" == "CHANGEME" ]]; then
    # generate flask secret key
    INDIALLSKY_FLASK_SECRET_KEY=$(${PYTHON_BIN} -c 'import secrets; print(secrets.token_hex())')

    TMP_FLASK_SKEY=$(mktemp --suffix=.json)
    jq --arg secret_key "$INDIALLSKY_FLASK_SECRET_KEY" '.SECRET_KEY = $secret_key' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_SKEY"
    cp -f "$TMP_FLASK_SKEY" "${ALLSKY_ETC}/flask.json"
    [[ -f "$TMP_FLASK_SKEY" ]] && rm -f "$TMP_FLASK_SKEY"
fi


INDIALLSKY_FLASK_PASSWORD_KEY=$(jq -r '.PASSWORD_KEY' "${ALLSKY_ETC}/flask.json")
if [[ -z "$INDIALLSKY_FLASK_PASSWORD_KEY" || "$INDIALLSKY_FLASK_PASSWORD_KEY" == "CHANGEME" ]]; then
    # generate password key for encryption
    INDIALLSKY_FLASK_PASSWORD_KEY=$(${PYTHON_BIN} -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')

    TMP_FLASK_PKEY=$(mktemp --suffix=.json)
    jq --arg password_key "$INDIALLSKY_FLASK_PASSWORD_KEY" '.PASSWORD_KEY = $password_key' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_PKEY"
    cp -f "$TMP_FLASK_PKEY" "${ALLSKY_ETC}/flask.json"
    [[ -f "$TMP_FLASK_PKEY" ]] && rm -f "$TMP_FLASK_PKEY"
fi


sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/flask.json"
sudo chmod 660 "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP_FLASK" ]] && rm -f "$TMP_FLASK"
[[ -f "$TMP_FLASK_MERGE" ]] && rm -f "$TMP_FLASK_MERGE"



# create a backup of the key
if [ ! -f "${ALLSKY_ETC}/password_key_backup.json" ]; then
    jq -n --arg password_key "$INDIALLSKY_PASSWORD_KEY" '.PASSWORD_KEY_BACKUP = $password_key' '{}' > "${ALLSKY_ETC}/password_key_backup.json"
fi

chmod 400 "${ALLSKY_ETC}/password_key_backup.json"



echo "**** Setup DB ****"
[[ ! -d "$DB_FOLDER" ]] && sudo mkdir -p "$DB_FOLDER"
sudo chmod 775 "$DB_FOLDER"
sudo chown -R "$USER":"$PGRP" "$DB_FOLDER"
[[ ! -d "${DB_FOLDER}/backup" ]] && sudo mkdir "${DB_FOLDER}/backup"
sudo chmod 775 "$DB_FOLDER/backup"
sudo chown "$USER":"$PGRP" "${DB_FOLDER}/backup"
if [[ -f "${DB_FILE}" ]]; then
    sudo chmod 664 "${DB_FILE}"
    sudo chown "$USER":"$PGRP" "${DB_FILE}"

    echo "**** Backup DB prior to migration ****"
    DB_BACKUP="${DB_FOLDER}/backup/backup_indi-allsky_$(date +%Y%m%d_%H%M%S).sqlite"
    sqlite3 "${DB_FILE}" ".backup ${DB_BACKUP}"
    gzip "$DB_BACKUP"

    chmod 640 "${DB_BACKUP}.gz"

    echo "**** Vacuum DB ****"
    sqlite3 "${DB_FILE}" "VACUUM;"
fi


# Setup migration folder
if [[ ! -d "$MIGRATION_FOLDER" ]]; then
    # Folder defined in flask config
    flask db init

    # Move migrations out of git checkout
    cd "${ALLSKY_DIRECTORY}/migrations/versions" || catch_error
    find . -type f -name "*.py" | cpio -pdmu "${MIGRATION_FOLDER}/versions"
    cd "$OLDPWD" || catch_error

    # Cleanup old files
    find "${ALLSKY_DIRECTORY}/migrations/versions" -type f -name "*.py" -exec rm -f {} \;
fi


cd "$ALLSKY_DIRECTORY" || catch_error
flask db revision --autogenerate
flask db upgrade head
cd "$OLDPWD" || catch_error


sudo chmod 664 "${DB_FILE}"
sudo chown "$USER":"$PGRP" "${DB_FILE}"


# some schema changes require data to be populated
echo "**** Populate database fields ****"
"${ALLSKY_DIRECTORY}/misc/populate_data.py"


if [ -f "${ALLSKY_ETC}/config.json" ]; then
    echo
    echo
    echo "Configurations are now being stored in the database"
    echo "This script will move your existing configuration into"
    echo "the database."
    echo
    sleep 5

    "${ALLSKY_DIRECTORY}/config.py" load -c "${ALLSKY_ETC}/config.json"

    mv -f "${ALLSKY_ETC}/config.json" "${ALLSKY_ETC}/legacy_config.json"

    # Move old backup config
    if [ -f "${ALLSKY_ETC}/config.json_old" ]; then
        mv -f "${ALLSKY_ETC}/config.json_old" "${ALLSKY_ETC}/legacy_config.json_old"
    fi
fi


### Mysql
if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
    sudo cp -f "${ALLSKY_DIRECTORY}/service/mysql_indi-allsky.conf" "$MYSQL_ETC/mariadb.conf.d/90-mysql_indi-allsky.conf"
    sudo chown root:root "$MYSQL_ETC/mariadb.conf.d/90-mysql_indi-allsky.conf"
    sudo chmod 644 "$MYSQL_ETC/mariadb.conf.d/90-mysql_indi-allsky.conf"

    if [[ ! -d "$MYSQL_ETC/ssl" ]]; then
        sudo mkdir "$MYSQL_ETC/ssl"
    fi

    sudo chown root:root "$MYSQL_ETC/ssl"
    sudo chmod 755 "$MYSQL_ETC/ssl"


    if [[ ! -e "$MYSQL_ETC/ssl/indi-allsky_mysql.key" || ! -e "$MYSQL_ETC/ssl/indi-allsky_mysq.pem" ]]; then
        sudo rm -f "$MYSQL_ETC/ssl/indi-allsky_mysql.key"
        sudo rm -f "$MYSQL_ETC/ssl/indi-allsky_mysql.pem"

        SHORT_HOSTNAME=$(hostname -s)
        MYSQL_KEY_TMP=$(mktemp --suffix=.key)
        MYSQL_CRT_TMP=$(mktemp --suffix=.pem)

        # sudo has problems with process substitution <()
        openssl req \
            -new \
            -newkey rsa:4096 \
            -sha512 \
            -days 3650 \
            -nodes \
            -x509 \
            -subj "/CN=${SHORT_HOSTNAME}.local" \
            -keyout "$MYSQL_KEY_TMP" \
            -out "$MYSQL_CRT_TMP" \
            -extensions san \
            -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

        sudo cp -f "$MYSQL_KEY_TMP" "$MYSQL_ETC/ssl/indi-allsky_mysql.key"
        sudo cp -f "$MYSQL_CRT_TMP" "$MYSQL_ETC/ssl/indi-allsky_mysql.pem"

        rm -f "$MYSQL_KEY_TMP"
        rm -f "$MYSQL_CRT_TMP"
    fi


    sudo chown root:root "$MYSQL_ETC/ssl/indi-allsky_mysql.key"
    sudo chmod 600 "$MYSQL_ETC/ssl/indi-allsky_mysql.key"
    sudo chown root:root "$MYSQL_ETC/ssl/indi-allsky_mysql.pem"
    sudo chmod 644 "$MYSQL_ETC/ssl/indi-allsky_mysql.pem"

    # system certificate store
    sudo cp -f "$MYSQL_ETC/ssl/indi-allsky_mysql.pem" /usr/local/share/ca-certificates/indi-allsky_mysql.crt
    sudo chown root:root /usr/local/share/ca-certificates/indi-allsky_mysql.crt
    sudo chmod 644 /usr/local/share/ca-certificates/indi-allsky_mysql.crt
    sudo update-ca-certificates


    sudo systemctl enable mariadb
    sudo systemctl restart mariadb
fi


# bootstrap initial config
"${ALLSKY_DIRECTORY}/config.py" bootstrap || true


# dump config for processing
TMP_CONFIG_DUMP=$(mktemp --suffix=.json)
"${ALLSKY_DIRECTORY}/config.py" dumpfile --outfile "$TMP_CONFIG_DUMP"


# Detect location
LOCATION_LATITUDE=$(jq -r '.LOCATION_LATITUDE' "$TMP_CONFIG_DUMP")
LOCATION_LONGITUDE=$(jq -r '.LOCATION_LONGITUDE' "$TMP_CONFIG_DUMP")


while [ -z "${LOCATION_LATITUDE_INPUT:-}" ]; do
    # shellcheck disable=SC2068
    LOCATION_LATITUDE_INPUT=$(whiptail --title "Latitude" --nocancel --inputbox "Please enter your latitude [90.0 to -90.0].  Positive values for the Northern Hemisphere, negative values for the Southern Hemisphere" 0 0 -- "$LOCATION_LATITUDE" 3>&1 1>&2 2>&3)
    if [[ "$LOCATION_LATITUDE_INPUT" =~ ^[+-]?[0-9]{3}$ ]]; then
        unset LOCATION_LATITUDE_INPUT
        whiptail --msgbox "Error: Invalid latitude" 0 0
        continue
    fi

    if ! [[ "$LOCATION_LATITUDE_INPUT" =~ ^[+-]?[0-9]{1,2}\.?[0-9]*$ ]]; then
        unset LOCATION_LATITUDE_INPUT
        whiptail --msgbox "Error: Invalid latitude" 0 0
        continue
    fi

    if [[ $(echo "$LOCATION_LATITUDE_INPUT < -90" | bc -l) -eq 1 || $(echo "$LOCATION_LATITUDE_INPUT > 90" | bc -l) -eq 1 ]]; then
        unset LOCATION_LATITUDE_INPUT
        whiptail --msgbox "Error: Invalid latitude" 0 0
        continue
    fi
done

while [ -z "${LOCATION_LONGITUDE_INPUT:-}" ]; do
    # shellcheck disable=SC2068
    LOCATION_LONGITUDE_INPUT=$(whiptail --title "Longitude" --nocancel --inputbox "Please enter your longitude [-180.0 to 180.0].  Negative values for the Western Hemisphere, positive values for the Eastern Hemisphere" 0 0 -- "$LOCATION_LONGITUDE" 3>&1 1>&2 2>&3)
    if [[ "$LOCATION_LATITUDE_INPUT" =~ ^[+-]?[0-9]{4}$ ]]; then
        unset LOCATION_LONGITUDE_INPUT
        whiptail --msgbox "Error: Invalid longitude" 0 0
        continue
    fi

    if ! [[ "$LOCATION_LONGITUDE_INPUT" =~ ^[+-]?[0-9]{1,3}\.?[0-9]*$ ]]; then
        unset LOCATION_LONGITUDE_INPUT
        whiptail --msgbox "Error: Invalid longitude" 0 0
        continue
    fi

    if [[ $(echo "$LOCATION_LONGITUDE_INPUT < -180" | bc -l) -eq 1 || $(echo "$LOCATION_LONGITUDE_INPUT > 180" | bc -l) -eq 1 ]]; then
        unset LOCATION_LONGITUDE_INPUT
        whiptail --msgbox "Error: Invalid longitude" 0 0
        continue
    fi
done


TMP_LOCATION=$(mktemp --suffix=.json)
jq \
    --argjson latitude "$LOCATION_LATITUDE_INPUT" \
    --argjson longitude "$LOCATION_LONGITUDE_INPUT" \
    '.LOCATION_LATITUDE = $latitude | .LOCATION_LONGITUDE = $longitude' "${TMP_CONFIG_DUMP}" > "$TMP_LOCATION"

cat "$TMP_LOCATION" > "$TMP_CONFIG_DUMP"

[[ -f "$TMP_LOCATION" ]] && rm -f "$TMP_LOCATION"



if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "ubuntu" || "$DISTRO_ID" == "raspbian" || "$DISTRO_ID" == "linuxmint" ]]; then
    # reconfigure system timezone
    if [ -n "${INDIALLSKY_TIMEZONE:-}" ]; then
        # this is not validated
        echo
        echo "Setting timezone to $INDIALLSKY_TIMEZONE"
        echo "$INDIALLSKY_TIMEZONE" | sudo tee /etc/timezone
        sudo dpkg-reconfigure -f noninteractive tzdata
    else
        sudo dpkg-reconfigure tzdata
    fi
else
    echo "Unable to set timezone for distribution"
    exit 1
fi


# Detect IMAGE_FOLDER
IMAGE_FOLDER=$(jq -r '.IMAGE_FOLDER' "$TMP_CONFIG_DUMP")


# Detect VARLIB_FOLDER
# This will not change the location of the database
VARLIB_FOLDER=$(jq -r '.VARLIB_FOLDER' "$TMP_CONFIG_DUMP")
if [ "${VARLIB_FOLDER:-null}" == "null" ]; then
    VARLIB_FOLDER="/var/lib/indi-allsky"
fi


echo
echo
echo "Detected IMAGE_FOLDER: $IMAGE_FOLDER"
echo "Detected VARLIB_FOLDER: $VARLIB_FOLDER"
sleep 3


# replace the flask IMAGE_FOLDER
TMP_FLASK_3=$(mktemp --suffix=.json)
jq --arg image_folder "$IMAGE_FOLDER" '.INDI_ALLSKY_IMAGE_FOLDER = $image_folder' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_3"
cp -f "$TMP_FLASK_3" "${ALLSKY_ETC}/flask.json"
[[ -f "$TMP_FLASK_3" ]] && rm -f "$TMP_FLASK_3"


TMP_GUNICORN=$(mktemp)
cat "${ALLSKY_DIRECTORY}/service/gunicorn.conf.py" > "$TMP_GUNICORN"

cp -f "$TMP_GUNICORN" "${ALLSKY_ETC}/gunicorn.conf.py"
chmod 644 "${ALLSKY_ETC}/gunicorn.conf.py"
[[ -f "$TMP_GUNICORN" ]] && rm -f "$TMP_GUNICORN"


if [[ "$WEBSERVER" == "nginx" && "$ASTROBERRY" == "true" ]]; then
    #echo "**** Disabling apache web server (Astroberry) ****"
    #sudo systemctl stop apache2 || true
    #sudo systemctl disable apache2 || true


    echo "**** Setup nginx ****"
    TMP_HTTP=$(mktemp)
    sed \
     -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
     -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
     -e "s|%DOCROOT_FOLDER%|$DOCROOT_FOLDER|g" \
     -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
     -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
     -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
     -e "s|%UPSTREAM_SERVER%|unix:$DB_FOLDER/$GUNICORN_SERVICE_NAME.sock|g" \
     "${ALLSKY_DIRECTORY}/service/nginx_astroberry_ssl" > "$TMP_HTTP"


    sudo cp -f "$TMP_HTTP" /etc/nginx/sites-available/indi-allsky_ssl
    sudo chown root:root /etc/nginx/sites-available/indi-allsky_ssl
    sudo chmod 644 /etc/nginx/sites-available/indi-allsky_ssl
    sudo ln -s -f /etc/nginx/sites-available/indi-allsky_ssl /etc/nginx/sites-enabled/indi-allsky_ssl

    sudo systemctl enable nginx
    sudo systemctl restart nginx

elif [[ "$WEBSERVER" == "nginx" ]]; then
    if systemctl --quiet is-active apache2.service; then
        echo "!!! WARNING - apache2 is active - This might interfere with nginx !!!"
        sleep 3
    fi

    if systemctl --quiet is-active lighttpd.service; then
        echo "!!! WARNING - lighttpd is active - This might interfere with nginx !!!"
        sleep 3
    fi


    if [ -e "/etc/nginx/sites-enabled/indi-allsky.conf" ]; then
        while [ -z "${WEBSERVER_CONFIG:-}" ]; do
            if whiptail --title "Web Server Configuration" --yesno "Do you want to update the web server configuration?\n\nIf you have performed customizations to the nginx config, you should choose \"no\"\n\n(Hint: Most people should pick \"yes\")" 0 0; then
                WEBSERVER_CONFIG="true"
            else
                WEBSERVER_CONFIG="false"
            fi
        done
    else
        WEBSERVER_CONFIG="true"
    fi


    if [ "$WEBSERVER_CONFIG" == "true" ]; then
        echo "**** Setup nginx ****"
        TMP_HTTP=$(mktemp)
        sed \
         -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
         -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
         -e "s|%DOCROOT_FOLDER%|$DOCROOT_FOLDER|g" \
         -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
         -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
         -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
         -e "s|%UPSTREAM_SERVER%|unix:$DB_FOLDER/$GUNICORN_SERVICE_NAME.sock|g" \
         "${ALLSKY_DIRECTORY}/service/nginx_indi-allsky.conf" > "$TMP_HTTP"


        if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "ubuntu" || "$DISTRO_ID" == "raspbian" || "$DISTRO_ID" == "linuxmint" ]]; then
            if [ -f "/etc/nginx/sites-available/indi-allsky.conf" ]; then
                # backup existing config
                sudo cp -f "/etc/nginx/sites-available/indi-allsky.conf" "/etc/nginx/sites-available/indi-allsky.conf_backup_$(date +%Y%m%d_%H%M%S)"
            fi


            sudo cp -f "$TMP_HTTP" /etc/nginx/sites-available/indi-allsky.conf
            sudo chown root:root /etc/nginx/sites-available/indi-allsky.conf
            sudo chmod 644 /etc/nginx/sites-available/indi-allsky.conf
            sudo ln -s -f /etc/nginx/sites-available/indi-allsky.conf /etc/nginx/sites-enabled/indi-allsky.conf

            [[ -e "/etc/nginx/sites-enabled/default" ]] && sudo rm -f /etc/nginx/sites-enabled/default


            if [[ ! -d "/etc/nginx/ssl" ]]; then
                sudo mkdir /etc/nginx/ssl
            fi

            sudo chown root:root /etc/nginx/ssl
            sudo chmod 755 /etc/nginx/ssl


            if [[ ! -e "/etc/nginx/ssl/indi-allsky_nginx.key" || ! -e "/etc/nginx/ssl/indi-allsky_nginx.pem" ]]; then
                sudo rm -f /etc/nginx/ssl/indi-allsky_nginx.key
                sudo rm -f /etc/nginx/ssl/indi-allsky_nginx.pem

                SHORT_HOSTNAME=$(hostname -s)
                HTTP_KEY_TMP=$(mktemp --suffix=.key)
                HTTP_CRT_TMP=$(mktemp --suffix=.pem)

                # sudo has problems with process substitution <()
                openssl req \
                    -new \
                    -newkey rsa:4096 \
                    -sha512 \
                    -days 3650 \
                    -nodes \
                    -x509 \
                    -subj "/CN=${SHORT_HOSTNAME}.local" \
                    -keyout "$HTTP_KEY_TMP" \
                    -out "$HTTP_CRT_TMP" \
                    -extensions san \
                    -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

                sudo cp -f "$HTTP_KEY_TMP" /etc/nginx/ssl/indi-allsky_nginx.key
                sudo cp -f "$HTTP_CRT_TMP" /etc/nginx/ssl/indi-allsky_nginx.pem

                rm -f "$HTTP_KEY_TMP"
                rm -f "$HTTP_CRT_TMP"
            fi


            sudo chown root:root /etc/nginx/ssl/indi-allsky_nginx.key
            sudo chmod 600 /etc/nginx/ssl/indi-allsky_nginx.key
            sudo chown root:root /etc/nginx/ssl/indi-allsky_nginx.pem
            sudo chmod 644 /etc/nginx/ssl/indi-allsky_nginx.pem

            # system certificate store
            sudo cp -f /etc/nginx/ssl/indi-allsky_nginx.pem /usr/local/share/ca-certificates/indi-allsky_nginx.crt
            sudo chown root:root /usr/local/share/ca-certificates/indi-allsky_nginx.crt
            sudo chmod 644 /usr/local/share/ca-certificates/indi-allsky_nginx.crt
            sudo update-ca-certificates
        fi


        # Always do this
        sudo systemctl enable nginx
        sudo systemctl restart nginx
    fi

elif [[ "$WEBSERVER" == "apache" ]]; then
    if systemctl --quiet is-active nginx.service; then
        echo "!!! WARNING - nginx is active - This might interfere with apache !!!"
        sleep 3
    fi

    if systemctl --quiet is-active lighttpd.service; then
        echo "!!! WARNING - lighttpd is active - This might interfere with apache !!!"
        sleep 3
    fi


    if [ -e "/etc/apache2/sites-enabled/indi-allsky.conf" ]; then
        while [ -z "${WEBSERVER_CONFIG:-}" ]; do
            if whiptail --title "Web Server Configuration" --yesno "Do you want to update the web server configuration?\n\nIf you have performed customizations to the apache config, you should choose \"no\"\n\n(Hint: Most people should pick \"yes\")" 0 0; then
                WEBSERVER_CONFIG="true"
            else
                WEBSERVER_CONFIG="false"
            fi
        done
    else
        WEBSERVER_CONFIG="true"
    fi



    if [ "$WEBSERVER_CONFIG" == "true" ]; then
        echo "**** Start apache2 service ****"
        TMP_HTTP=$(mktemp)
        sed \
         -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
         -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
         -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
         -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
         -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
         -e "s|%UPSTREAM_SERVER%|unix:$DB_FOLDER/$GUNICORN_SERVICE_NAME.sock\|http://localhost/indi-allsky|g" \
         "${ALLSKY_DIRECTORY}/service/apache_indi-allsky.conf" > "$TMP_HTTP"


        if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "ubuntu" || "$DISTRO_ID" == "raspbian" || "$DISTRO_ID" == "linuxmint" ]]; then
            if [ -f "/etc/apache2/sites-available/indi-allsky.conf" ]; then
                # backup existing config
                sudo cp -f "/etc/apache2/sites-available/indi-allsky.conf" "/etc/apache2/sites-available/indi-allsky.backup_$(date +%Y%m%d_%H%M%S)"
            fi


            sudo cp -f "$TMP_HTTP" /etc/apache2/sites-available/indi-allsky.conf
            sudo chown root:root /etc/apache2/sites-available/indi-allsky.conf
            sudo chmod 644 /etc/apache2/sites-available/indi-allsky.conf


            if [[ ! -d "/etc/apache2/ssl" ]]; then
                sudo mkdir /etc/apache2/ssl
            fi

            sudo chown root:root /etc/apache2/ssl
            sudo chmod 755 /etc/apache2/ssl


            if [[ ! -e "/etc/apache2/ssl/indi-allsky_apache.key" || ! -e "/etc/apache2/ssl/indi-allsky_apache.pem" ]]; then
                sudo rm -f /etc/apache2/ssl/indi-allsky_apache.key
                sudo rm -f /etc/apache2/ssl/indi-allsky_apache.pem

                SHORT_HOSTNAME=$(hostname -s)
                HTTP_KEY_TMP=$(mktemp --suffix=.key)
                HTTP_CRT_TMP=$(mktemp --suffix=.pem)

                # sudo has problems with process substitution <()
                openssl req \
                    -new \
                    -newkey rsa:4096 \
                    -sha512 \
                    -days 3650 \
                    -nodes \
                    -x509 \
                    -subj "/CN=${SHORT_HOSTNAME}.local" \
                    -keyout "$HTTP_KEY_TMP" \
                    -out "$HTTP_CRT_TMP" \
                    -extensions san \
                    -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

                sudo cp -f "$HTTP_KEY_TMP" /etc/apache2/ssl/indi-allsky_apache.key
                sudo cp -f "$HTTP_CRT_TMP" /etc/apache2/ssl/indi-allsky_apache.pem

                rm -f "$HTTP_KEY_TMP"
                rm -f "$HTTP_CRT_TMP"
            fi


            sudo chown root:root /etc/apache2/ssl/indi-allsky_apache.key
            sudo chmod 600 /etc/apache2/ssl/indi-allsky_apache.key
            sudo chown root:root /etc/apache2/ssl/indi-allsky_apache.pem
            sudo chmod 644 /etc/apache2/ssl/indi-allsky_apache.pem

            # system certificate store
            sudo cp -f /etc/apache2/ssl/indi-allsky_apache.pem /usr/local/share/ca-certificates/indi-allsky_apache.crt
            sudo chown root:root /usr/local/share/ca-certificates/indi-allsky_apache.crt
            sudo chmod 644 /usr/local/share/ca-certificates/indi-allsky_apache.crt
            sudo update-ca-certificates


            sudo a2enmod rewrite
            sudo a2enmod headers
            sudo a2enmod ssl
            sudo a2enmod http2
            sudo a2enmod proxy
            sudo a2enmod proxy_http
            sudo a2enmod proxy_http2
            sudo a2enmod expires

            sudo a2dissite 000-default
            sudo a2dissite default-ssl

            sudo a2ensite indi-allsky

            if [[ ! -f "/etc/apache2/ports.conf_pre_indiallsky" ]]; then
                sudo cp /etc/apache2/ports.conf /etc/apache2/ports.conf_pre_indiallsky

                # Comment out the Listen directives
                TMP9=$(mktemp)
                sed \
                 -e 's|^\(.*\)[^#]\?\(listen.*\)|\1#\2|i' \
                 /etc/apache2/ports.conf_pre_indiallsky > "$TMP9"

                sudo cp -f "$TMP9" /etc/apache2/ports.conf
                sudo chown root:root /etc/apache2/ports.conf
                sudo chmod 644 /etc/apache2/ports.conf
                [[ -f "$TMP9" ]] && rm -f "$TMP9"
            fi
        fi


        # Always do this
        sudo systemctl enable apache2
        sudo systemctl restart apache2
    fi

else
    echo
    echo "Unknown web server: $WEBSERVER"
    echo

    exit 1
fi

[[ -f "$TMP_HTTP" ]] && rm -f "$TMP_HTTP"


# Allow web server access to mounted media
if [[ -d "/media/${USER}" ]]; then
    sudo chmod ugo+x "/media/${USER}"
fi


echo "**** Setup HTDOCS folder ****"
[[ ! -d "$HTDOCS_FOLDER" ]] && sudo mkdir "$HTDOCS_FOLDER"
sudo chmod 755 "$HTDOCS_FOLDER"
sudo chown -R "$USER":"$PGRP" "$HTDOCS_FOLDER"
[[ ! -d "$HTDOCS_FOLDER/js" ]] && mkdir "$HTDOCS_FOLDER/js"
chmod 775 "$HTDOCS_FOLDER/js"

for F in $HTDOCS_FILES; do
    cp -f "${ALLSKY_DIRECTORY}/html/${F}" "${HTDOCS_FOLDER}/${F}"
    chmod 664 "${HTDOCS_FOLDER}/${F}"
done


echo "**** Setup image folder ****"
[[ ! -d "$IMAGE_FOLDER" ]] && sudo mkdir -p "$IMAGE_FOLDER"
sudo chmod 775 "$IMAGE_FOLDER"
sudo chown -R "$USER":"$PGRP" "$IMAGE_FOLDER"
[[ ! -d "${IMAGE_FOLDER}/darks" ]] && mkdir "${IMAGE_FOLDER}/darks"
chmod 775 "${IMAGE_FOLDER}/darks"
[[ ! -d "${IMAGE_FOLDER}/export" ]] && mkdir "${IMAGE_FOLDER}/export"
chmod 775 "${IMAGE_FOLDER}/export"

if [ "$IMAGE_FOLDER" != "${ALLSKY_DIRECTORY}/html/images" ]; then
    for F in $IMAGE_FOLDER_FILES; do
        cp -f "${ALLSKY_DIRECTORY}/html/images/${F}" "${IMAGE_FOLDER}/${F}"
        chmod 664 "${IMAGE_FOLDER}/${F}"
    done
fi


echo "**** Setup varlib folder ****"
# This is not the database folder (even though it may be the same)
[[ ! -d "$VARLIB_FOLDER" ]] && sudo mkdir -p "$VARLIB_FOLDER"
sudo chmod 775 "$VARLIB_FOLDER"
sudo chown -R "$USER":"$PGRP" "$VARLIB_FOLDER"


# Disable raw frames with libcamera when running less than 1GB of memory
if [ "$MEM_TOTAL" -lt "768000" ]; then
    TMP_LIBCAM_TYPE=$(mktemp --suffix=.json)
    jq --arg libcamera_file_type "jpg" '.LIBCAMERA.IMAGE_FILE_TYPE = $libcamera_file_type' "$TMP_CONFIG_DUMP" > "$TMP_LIBCAM_TYPE"

    cat "$TMP_LIBCAM_TYPE" > "$TMP_CONFIG_DUMP"

    [[ -f "$TMP_LIBCAM_TYPE" ]] && rm -f "$TMP_LIBCAM_TYPE"
fi


echo "**** Ensure user is a member of special groups ****"
for GRP in dialout video plugdev gpio i2c spi adm; do
    if getent group "$GRP" >/dev/null 2>&1; then
        sudo usermod -a -G "$GRP" "$USER"
    fi
done


echo "**** Enable linger for user ****"
sudo loginctl enable-linger "$USER"


# Not trying to push out the competition, these just cannot run at the same time :-)
if systemctl list-unit-files "allsky.service" >/dev/null 2>&1; then
    echo "**** Disabling Thomas Jacquin's allsky (ignore errors) ****"
    sudo systemctl stop allsky || true
    sudo systemctl disable allsky || true
fi


echo "**** Starting ${GUNICORN_SERVICE_NAME}.socket"
# this needs to happen after creating the $DB_FOLDER
systemctl --user start "${GUNICORN_SERVICE_NAME}.socket"


echo "**** Update config camera interface ****"
TMP_CAMERA_INT=$(mktemp --suffix=.json)
jq --arg camera_interface "$CAMERA_INTERFACE" '.CAMERA_INTERFACE = $camera_interface' "$TMP_CONFIG_DUMP" > "$TMP_CAMERA_INT"

cat "$TMP_CAMERA_INT" > "$TMP_CONFIG_DUMP"

[[ -f "$TMP_CAMERA_INT" ]] && rm -f "$TMP_CAMERA_INT"


echo "**** Update indi port ****"
TMP_INDI_PORT=$(mktemp --suffix=.json)
jq --argjson indi_port "$INDI_PORT" '.INDI_PORT = $indi_port' "$TMP_CONFIG_DUMP" > "$TMP_INDI_PORT"

cat "$TMP_INDI_PORT" > "$TMP_CONFIG_DUMP"

[[ -f "$TMP_INDI_PORT" ]] && rm -f "$TMP_INDI_PORT"


# final config syntax check
json_pp < "$TMP_CONFIG_DUMP" > /dev/null


# load all changes
"${ALLSKY_DIRECTORY}/config.py" load -c "$TMP_CONFIG_DUMP" --force
[[ -f "$TMP_CONFIG_DUMP" ]] && rm -f "$TMP_CONFIG_DUMP"


# final config syntax check
json_pp < "${ALLSKY_ETC}/flask.json" > /dev/null


USER_COUNT=$("${ALLSKY_DIRECTORY}/config.py" user_count)
# there is a system user
if [ "$USER_COUNT" -le 1 ]; then
    while [ -z "${WEB_USER:-}" ]; do
        # shellcheck disable=SC2068
        WEB_USER=$(whiptail --title "Username" --nocancel --inputbox "Please enter a username to login" 0 0 3>&1 1>&2 2>&3)
    done

    while [ -z "${WEB_PASS:-}" ]; do
        # shellcheck disable=SC2068
        WEB_PASS=$(whiptail --title "Password" --nocancel --passwordbox "Please enter the password (8+ chars)" 0 0 3>&1 1>&2 2>&3)

        if [ "${#WEB_PASS}" -lt 8 ]; then
            WEB_PASS=""
            whiptail --msgbox "Error: Password needs to be at least 8 characters" 0 0
            continue
        fi


        WEB_PASS2=$(whiptail --title "Password (#2)" --nocancel --passwordbox "Please enter the password (8+ chars)" 0 0 3>&1 1>&2 2>&3)

        if [ "$WEB_PASS" != "$WEB_PASS2" ]; then
            WEB_PASS=""
            whiptail --msgbox "Error: Passwords did not match" 0 0
            continue
        fi

    done

    while [ -z "${WEB_NAME:-}" ]; do
        # shellcheck disable=SC2068
        WEB_NAME=$(whiptail --title "Full Name" --nocancel --inputbox "Please enter the users name" 0 0 3>&1 1>&2 2>&3)
    done

    while [ -z "${WEB_EMAIL:-}" ]; do
        # shellcheck disable=SC2068
        WEB_EMAIL=$(whiptail --title "Email" --nocancel --inputbox "Please enter the users email\n\nThe email address is only stored on your local system and is not transmitted" 0 0 3>&1 1>&2 2>&3)
    done

    "$ALLSKY_DIRECTORY/misc/usertool.py" adduser -u "$WEB_USER" -p "$WEB_PASS" -f "$WEB_NAME" -e "$WEB_EMAIL"
    "$ALLSKY_DIRECTORY/misc/usertool.py" setadmin -u "$WEB_USER"
fi


if [ "$INSTALL_INDISERVER" == "true" ]; then
    systemctl --user enable "${INDISERVER_SERVICE_NAME}.timer"
    # indiserver service is started by the timer (30 seconds after boot)
    systemctl --user disable "${INDISERVER_SERVICE_NAME}.service"


    while [ -z "${RESTART_INDISERVER:-}" ]; do
        if whiptail --title "Restart indiserver" --yesno "Do you want to restart the indiserver now?\n\nNot recommended if the indi-allsky service is active." 0 0 --defaultno; then
            RESTART_INDISERVER="true"
        else
            RESTART_INDISERVER="false"
        fi
    done


    if [ "$RESTART_INDISERVER" == "true" ]; then
        echo "Restarting indiserver..."
        sleep 3
        systemctl --user restart "${INDISERVER_SERVICE_NAME}.service"
    fi
fi


# ensure indiserver is running
systemctl --user start "${INDISERVER_SERVICE_NAME}.service"


# ensure latest code is active
systemctl --user restart "${GUNICORN_SERVICE_NAME}.service"


# disable ModemManager
echo "*** Disable ModemManger ***"
if systemctl --quiet is-enabled "ModemManager.service" 2>/dev/null; then
    sudo systemctl stop ModemManager
    sudo systemctl disable ModemManager
fi


# MQTT setup
if systemctl --quiet is-active "mosquitto.service" >/dev/null 2>&1; then
    INSTALL_MOSQUITTO="false"
    echo
    echo "Mosquitto MQTT broker is already installed"
fi

while [ -z "${INSTALL_MOSQUITTO:-}" ]; do
    if whiptail --title "MQTT Broker Setup" --yesno "Would you like to install and setup the mosquitto MQTT broker?" 0 0 --defaultno; then
        INSTALL_MOSQUITTO="true"
    else
        INSTALL_MOSQUITTO="false"
    fi
done

if [ "$INSTALL_MOSQUITTO" == "true" ]; then
    "$ALLSKY_DIRECTORY/misc/setup_mosquitto_mqtt.sh"
fi


while [ -z "${INDIALLSKY_AUTOSTART:-}" ]; do
    if whiptail --title "Auto-start indi-allsky" --yesno "Do you want to start indi-allsky automatically at boot?" 0 0; then
        INDIALLSKY_AUTOSTART="true"
    else
        INDIALLSKY_AUTOSTART="false"
    fi
done


if [ "$INDIALLSKY_AUTOSTART" == "true" ]; then
    systemctl --user enable "${ALLSKY_SERVICE_NAME}.timer"
else
    systemctl --user disable "${ALLSKY_SERVICE_NAME}.timer"
fi



if systemctl --user --quiet is-active "${ALLSKY_SERVICE_NAME}.service" >/dev/null 2>&1; then
    # no need to start if already running
    INDIALLSKY_START="false"
fi


while [ -z "${INDIALLSKY_START:-}" ]; do
    if whiptail --title "Start indi-allsky" --yesno "Do you want to start indi-allsky service now?" 0 0 --defaultno; then
        INDIALLSKY_START="true"
    else
        INDIALLSKY_START="false"
    fi
done


while [ -z "${INDIALLSKY_DISABLE_LEDS:-}" ]; do
    if whiptail --title "Disable Activity LEDs" --yesno "Would you like to disable the system activity LEDs at boot?" 0 0 --defaultno; then
        INDIALLSKY_DISABLE_LEDS="true"
    else
        INDIALLSKY_DISABLE_LEDS="false"
    fi
done


if [ "$INDIALLSKY_DISABLE_LEDS" == "true" ]; then
    "${ALLSKY_DIRECTORY}/misc/setup_disable_leds.sh" || true
fi


while [ -z "${INDIALLSKY_ENABLE_WATCHDOG:-}" ]; do
    if whiptail --title "Enable Watchdog" --yesno "Would you like to enable the SystemD watchdog daemon?\n\nThis will automatically reboot your system if it becomes unresponsive." 0 0 --defaultno; then
        INDIALLSKY_ENABLE_WATCHDOG="true"
    else
        INDIALLSKY_ENABLE_WATCHDOG="false"
    fi
done


if [ "$INDIALLSKY_ENABLE_WATCHDOG" == "true" ]; then
    [[ ! -d "/etc/systemd/system.conf.d" ]] && sudo mkdir -m 755 "/etc/systemd/system.conf.d"
    sudo chown root:root "/etc/systemd/system.conf.d"

    sudo tee /etc/systemd/system.conf.d/indi-allsky-watchdog.conf <<EOF
[Manager]
RuntimeWatchdogSec=10
ShutdownWatchdogSec=10min
EOF

    sudo chown root:root "/etc/systemd/system.conf.d/indi-allsky-watchdog.conf"
    sudo chmod 644 "/etc/systemd/system.conf.d/indi-allsky-watchdog.conf"
fi


if [ "$INDIALLSKY_START" == "true" ]; then
    echo "Starting indi-allsky..."
    sleep 3
    systemctl --user start "${ALLSKY_SERVICE_NAME}.service"
fi


while [ -z "${INDIALLSKY_SYSTEM_OPTIMIZE:-}" ]; do
    if whiptail --title "Setup System Optimizations" --yesno "Would you like to apply some common optimizations to your system for better performance?" 0 0 --defaultno; then
        INDIALLSKY_SYSTEM_OPTIMIZE="true"
    else
        INDIALLSKY_SYSTEM_OPTIMIZE="false"
    fi
done


if [ "$INDIALLSKY_SYSTEM_OPTIMIZE" == "true" ]; then
    echo
    echo "Setting up optimizations..."

    ### reduces unnecessary swapping
    sudo tee /etc/sysctl.d/90-indi-allsky.conf <<EOF
vm.swappiness = 1
EOF

    sudo sysctl --system


    ### reduces disk i/o for system journal
    [[ ! -d "/etc/systemd/journald.conf.d" ]] && sudo mkdir -m 755 "/etc/systemd/journald.conf.d"
    sudo chown root:root "/etc/systemd/journald.conf.d"
    sudo tee "/etc/systemd/journald.conf.d/90-indi-allsky.conf" <<EOF
[Journal]
Storage=volatile
Compress=yes
RateLimitIntervalSec=30s
RateLimitBurst=10000
SystemMaxUse=20M
EOF

    sudo chown root:root "/etc/systemd/journald.conf.d/90-indi-allsky.conf"
    sudo chmod 644 "/etc/systemd/journald.conf.d/90-indi-allsky.conf"

    sudo systemctl restart systemd-journald
    sleep 3
fi


SYSTEM_RUNLEVEL=$(systemctl get-default)
if [ "$SYSTEM_RUNLEVEL" == "graphical.target" ]; then
    while [ -z "${INDIALLSKY_MULTIUSER_RUNLEVEL:-}" ]; do
        if whiptail --title "Runlevel" --yesno "The operating system is currently configured to boot using the graphical user interface.  Disabling the operating system GUI can save system resources for better performance.\n\nWould you like to disable the OS GUI Interface? (Change will be made active on next reboot)" 0 0 --defaultno; then
            INDIALLSKY_MULTIUSER_RUNLEVEL="true"
        else
            INDIALLSKY_MULTIUSER_RUNLEVEL="false"
        fi
    done
fi


if [ "$INDIALLSKY_MULTIUSER_RUNLEVEL" == "true" ]; then
    echo
    echo "Switching to multi-user.target (runlevel 3)"
    sudo systemctl set-default multi-user.target
    #sudo systemctl isolate multi-user.target
    sleep 3
fi


echo
echo "Setup indi-allsky virtualenv pth"
"${ALLSKY_DIRECTORY}/misc/add_indi_allsky_pth.py"


echo
echo
echo

echo "Optional task: Reconfigure your devices localization settings:"
echo
echo "    sudo dpkg-reconfigure locales"


if [ ! "$INDIALLSKY_START" == "true" ]; then
    echo
    echo
    echo "Services may be started at the command line or can be started from the web interface"
    echo
    echo "    systemctl --user start indi-allsky"
fi

echo
echo
echo "The web interface may be accessed with the following URL"
echo " (You may have to manually access by IP)"
echo

if [[ "$HTTPS_PORT" -eq 443 ]]; then
    echo "    https://$(hostname -s).local/indi-allsky/"
else
    echo "    https://$(hostname -s).local:$HTTPS_PORT/indi-allsky/"

fi


END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo

echo
echo "Enjoy!"
