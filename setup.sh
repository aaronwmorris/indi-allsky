#!/bin/bash

#set -x  # command tracing
#set -o errexit  # replace by trapping ERR
#set -o nounset  # problems with python virtualenvs

PATH=/usr/bin:/bin
export PATH


#### config ####
INDI_ALLSKY_VERSION="20221023.0"
INDI_DRIVER_PATH="/usr/bin"
INDISEVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"
ALLSKY_ETC="/etc/indi-allsky"
DOCROOT_FOLDER="/var/www/html"
HTDOCS_FOLDER="${DOCROOT_FOLDER}/allsky"
DB_FOLDER="/var/lib/indi-allsky"
DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"
DB_URI_DEFAULT="sqlite:///${DB_FILE}"
INSTALL_INDI="true"
INSTALL_LIBCAMERA="false"
HTTP_PORT="80"
HTTPS_PORT="443"
DPC_STRENGTH="0"
#### end config ####


### libcamera Defective Pixel Correction (DPC) Strength
# https://datasheets.raspberrypi.com/camera/raspberry-pi-camera-guide.pdf
#
# 0 = Off
# 1 = Normal correction (default)
# 2 = Strong correction
###



function catch_error() {
    echo
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
    echo "The setup script was interrupted, please run the script again to finish..."
    echo
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


DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)

# get primary group
PGRP=$(id -ng)


echo "###############################################"
echo "### Welcome to the indi-allsky setup script ###"
echo "###############################################"


if [ -f "/usr/local/bin/indiserver" ]; then
    # Do not install INDI
    INSTALL_INDI="false"
    INDI_DRIVER_PATH="/usr/local/bin"

    echo
    echo
    echo "Detected a custom installation of INDI in /usr/local/bin"
    echo
    echo
    sleep 3
fi


if [[ -f "/etc/astroberry.version" ]]; then
    ASTROBERRY="true"
    echo
    echo
    echo "Detected Astroberry server"
    echo

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
else
    ASTROBERRY="false"
fi


if systemctl --user -q is-active indi-allsky >/dev/null 2>&1; then
    echo
    echo
    echo "WARNING: indi-allsky is running.  It is recommended to stop the service before running this script."
    echo
    sleep 5
fi


echo
echo
echo "Distribution: $DISTRO_NAME"
echo "Release: $DISTRO_RELEASE"
echo "Arch: $CPU_ARCH"
echo
echo "INDI_DRIVER_PATH: $INDI_DRIVER_PATH"
echo "INDISERVER_SERVICE_NAME: $INDISEVER_SERVICE_NAME"
echo "ALLSKY_SERVICE_NAME: $ALLSKY_SERVICE_NAME"
echo "GUNICORN_SERVICE_NAME: $GUNICORN_SERVICE_NAME"
echo "ALLSKY_ETC: $ALLSKY_ETC"
echo "HTDOCS_FOLDER: $HTDOCS_FOLDER"
echo "DB_FOLDER: $DB_FOLDER"
echo "DB_FILE: $DB_FILE"
echo "INSTALL_INDI: $INSTALL_INDI"
echo "HTTP_PORT: $HTTP_PORT"
echo "HTTPS_PORT: $HTTPS_PORT"
echo
echo

if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run $(basename $0) as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi

if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "Please do not run $(basename $0) with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
    echo
    echo
    exit 1
fi

echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


START_TIME=$(date +%s)


echo
echo
echo "indi-allsky supports the following camera interfaces."
echo
echo "Note:  libcamera is generally only available on ARM SoCs like Raspberry Pi"
echo
PS3="Select a camera interface: "
select camera_interface in indi libcamera_imx477; do
    if [ -n "$camera_interface" ]; then
        CAMERA_INTERFACE=$camera_interface
        break
    fi
done



if [ "$CAMERA_INTERFACE" == "libcamera_imx477" ]; then
    INSTALL_LIBCAMERA="true"
fi


echo
echo
echo "Fixing git checkout permissions"
sudo find "$(dirname $0)" ! -user "$USER" -exec chown "$USER" {} \;
sudo find "$(dirname $0)" -type d ! -perm -555 -exec chmod ugo+rx {} \;
sudo find "$(dirname $0)" -type f ! -perm -444 -exec chmod ugo+r {} \;



echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data

    PYTHON_BIN=python3

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on arm 32bit
        VIRTUALENV_REQ=requirements_debian11_armv7l.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    if [[ "$CPU_ARCH" == "aarch64" ]]; then
        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            sudo su -c "echo 'deb https://www.astroberry.io/repo/ bullseye main' > /etc/apt/sources.list.d/astroberry.list"
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
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        libgnutls28-dev \
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
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
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
            indi-sx
    fi

    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        sudo apt-get -y install \
            libcamera-apps
    fi


elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data

    PYTHON_BIN=python3

    VIRTUALENV_REQ=requirements_debian10.txt


    if [ "$CAMERA_INTERFACE" == "libcamera_imx477" ]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    if [[ "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            sudo su -c "echo 'deb https://www.astroberry.io/repo/ buster main' > /etc/apt/sources.list.d/astroberry.list"
        fi
    fi


    sudo apt-get update
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
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
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
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            indi-rpicam \
            libindi-dev \
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
            indi-sx
    fi

    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        sudo apt-get -y install \
            libcamera-apps
    fi

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data

    PYTHON_BIN=python3

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on arm 32bit
        VIRTUALENV_REQ=requirements_debian11_armv7l.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    # Sometimes raspbian can be detected as debian
    if [[ "$CPU_ARCH" == "aarch64" ]]; then
        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            sudo su -c "echo 'deb https://www.astroberry.io/repo/ bullseye main' > /etc/apt/sources.list.d/astroberry.list"
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
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        libgnutls28-dev \
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
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
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
            indi-sx
    fi


    if [[ "$INSTALL_LIBCAMERA" == "true" ]]; then
        # this can fail on armbian debian based repos
        sudo apt-get -y install \
            libcamera-apps || true
    fi


elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data

    PYTHON_BIN=python3

    VIRTUALENV_REQ=requirements_debian10.txt


    if [ "$CAMERA_INTERFACE" == "libcamera_imx477" ]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    # Sometimes raspbian can be detected as debian
    if [[ "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            sudo su -c "echo 'deb https://www.astroberry.io/repo/ buster main' > /etc/apt/sources.list.d/astroberry.list"
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


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    sudo apt-get update
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
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
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
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            indi-rpicam \
            libindi-dev \
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
            indi-sx
    fi

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "22.04" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data

    PYTHON_BIN=python3

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on arm 32bit
        VIRTUALENV_REQ=requirements_debian11_armv7l.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi


    if [ "$CAMERA_INTERFACE" == "libcamera_imx477" ]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    if [[ "$CPU_ARCH" == "x86_64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository ppa:mutlaqja/ppa
        fi
    elif [[ "$CPU_ARCH" == "aarch64" || "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
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


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    sudo apt-get update
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
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        libgnutls28-dev \
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
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
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
            indi-sx
    fi


elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data

    PYTHON_BIN=python3.9

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on arm 32bit
        VIRTUALENV_REQ=requirements_debian11_armv7l.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi


    if [ "$CAMERA_INTERFACE" == "libcamera_imx477" ]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    if [[ "$CPU_ARCH" == "x86_64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository ppa:mutlaqja/ppa
        fi
    elif [[ "$CPU_ARCH" == "aarch64" || "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
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


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3.9 \
        python3.9-dev \
        python3.9-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
        libgnutls28-dev \
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
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
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
            indi-sx
    fi

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "18.04" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data

    PYTHON_BIN=python3.8

    if [ "$CPU_ARCH" == "armv7l" ]; then
        # rawpy not available on arm 32bit
        VIRTUALENV_REQ=requirements_debian11_armv7l.txt
    else
        VIRTUALENV_REQ=requirements_debian11.txt
    fi



    if [ "$CAMERA_INTERFACE" == "libcamera_imx477" ]; then
        echo
        echo
        echo "libcamera is not supported in this distribution"
        exit 1
    fi


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    if [[ "$CPU_ARCH" == "x86_64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            sudo add-apt-repository ppa:mutlaqja/ppa
        fi
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3.8 \
        python3.8-dev \
        python3.8-venv \
        python3-pip \
        virtualenv \
        cmake \
        gfortran \
        whiptail \
        rsyslog \
        cron \
        git \
        cpio \
        tzdata \
        ca-certificates \
        avahi-daemon \
        apache2 \
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
        zlib1g-dev \
        libgnutls28-dev \
        libdbus-1-dev \
        libglib2.0-dev \
        libffi-dev \
        libopencv-dev \
        libopenblas-dev \
        pkg-config \
        rustc \
        cargo \
        ffmpeg \
        gifsicle \
        jq \
        sqlite3 \
        policykit-1 \
        dbus-user-session


    if [[ "$INSTALL_INDI" == "true" ]]; then
        sudo apt-get -y install \
            indi-full \
            libindi-dev \
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
            indi-sx
    fi

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    echo
    echo
    echo "The DBUS user session is not defined"
    echo
    echo "Now that the dbus package has been installed..."
    echo "Please reboot your system and re-run this script to continue"
    echo
    exit 1
fi



# get list of drivers
cd "$INDI_DRIVER_PATH"
INDI_DRIVERS=$(ls indi_*_ccd indi_rpicam 2>/dev/null || true)
cd "$OLDPWD"


# find script directory for service setup
SCRIPT_DIR=$(dirname $0)
cd "$SCRIPT_DIR"
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD"


echo "**** Ensure path to git folder is traversable ****"
# Web servers running as www-data or nobody need to be able to read files in the git checkout
PARENT_DIR="$ALLSKY_DIRECTORY"
while [ 1 ]; do
    if [ "$PARENT_DIR" == "/" ]; then
        break
    elif [ "$PARENT_DIR" == "." ]; then
        break
    fi

    echo "Setting other execute bit on $PARENT_DIR"
    sudo chmod ugo+x "$PARENT_DIR"

    PARENT_DIR=$(dirname "$PARENT_DIR")
done


echo "**** Python virtualenv setup ****"
[[ ! -d "${ALLSKY_DIRECTORY}/virtualenv" ]] && mkdir "${ALLSKY_DIRECTORY}/virtualenv"
chmod 775 "${ALLSKY_DIRECTORY}/virtualenv"
if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky" ]; then
    virtualenv -p "${PYTHON_BIN}" "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky"
fi
source ${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate
pip3 install --upgrade pip setuptools wheel
pip3 install -r "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ}"


if [ "$CAMERA_INTERFACE" == "indi" ]; then
    echo
    echo
    PS3="Select an INDI driver: "
    select indi_driver_path in $INDI_DRIVERS; do
        if [ -f "${INDI_DRIVER_PATH}/${indi_driver_path}" ]; then
            CCD_DRIVER=$indi_driver_path
            break
        fi
    done
else
    # simulator will not affect anything
    CCD_DRIVER=indi_ccd_simulator
fi

#echo $CCD_DRIVER


# create users systemd folder
[[ ! -d "${HOME}/.config/systemd/user" ]] && mkdir -p "${HOME}/.config/systemd/user"

echo
echo
echo "**** Setting up indiserver service ****"
TMP1=$(mktemp)
sed \
 -e "s|%INDI_DRIVER_PATH%|$INDI_DRIVER_PATH|g" \
 -e "s|%INDISERVER_USER%|$USER|g" \
 -e "s|%INDI_CCD_DRIVER%|$CCD_DRIVER|g" \
 ${ALLSKY_DIRECTORY}/service/indiserver.service > $TMP1


cp -f "$TMP1" "${HOME}/.config/systemd/user/${INDISEVER_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${INDISEVER_SERVICE_NAME}.service"
[[ -f "$TMP1" ]] && rm -f "$TMP1"


echo "**** Setting up indi-allsky service ****"
TMP2=$(mktemp)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 ${ALLSKY_DIRECTORY}/service/indi-allsky.service > $TMP2

cp -f "$TMP2" "${HOME}/.config/systemd/user/${ALLSKY_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${ALLSKY_SERVICE_NAME}.service"
[[ -f "$TMP2" ]] && rm -f "$TMP2"


echo "**** Setting up gunicorn ****"
TMP5=$(mktemp)
sed \
 -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 ${ALLSKY_DIRECTORY}/service/gunicorn-indi-allsky.socket > $TMP5

cp -f "$TMP5" "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.socket"
chmod 644 "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.socket"
[[ -f "$TMP5" ]] && rm -f "$TMP5"

TMP6=$(mktemp)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 ${ALLSKY_DIRECTORY}/service/gunicorn-indi-allsky.service > $TMP6

cp -f "$TMP6" "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.service"
[[ -f "$TMP6" ]] && rm -f "$TMP6"


echo "**** Enabling services ****"
sudo loginctl enable-linger $USER
systemctl --user daemon-reload
systemctl --user enable ${INDISEVER_SERVICE_NAME}.service
systemctl --user enable ${ALLSKY_SERVICE_NAME}.service
systemctl --user enable ${GUNICORN_SERVICE_NAME}.socket
systemctl --user enable ${GUNICORN_SERVICE_NAME}.service


echo "**** Setup policy kit permissions ****"
TMP8=$(mktemp)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 ${ALLSKY_DIRECTORY}/service/90-org.aaronwmorris.indi-allsky.pkla > $TMP8

sudo cp -f "$TMP8" "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
sudo chown root:root "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
sudo chmod 644 "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
[[ -f "$TMP8" ]] && rm -f "$TMP8"


echo "**** Ensure user is a member of the systemd-journal group ****"
sudo usermod -a -G systemd-journal "$USER"


echo "**** Setup rsyslog logging ****"
[[ ! -d "/var/log/indi-allsky" ]] && sudo mkdir /var/log/indi-allsky
sudo chmod 755 /var/log/indi-allsky
sudo touch /var/log/indi-allsky/indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/indi-allsky.log
sudo touch /var/log/indi-allsky/webapp-indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/webapp-indi-allsky.log
sudo chown -R $RSYSLOG_USER:$RSYSLOG_GROUP /var/log/indi-allsky


# 10 prefix so they are process before the defaults in 50
sudo cp -f ${ALLSKY_DIRECTORY}/log/rsyslog_indi-allsky.conf /etc/rsyslog.d/10-indi-allsky.conf
sudo chown root:root /etc/rsyslog.d/10-indi-allsky.conf
sudo chmod 644 /etc/rsyslog.d/10-indi-allsky.conf

# remove old version
[[ -f "/etc/rsyslog.d/indi-allsky.conf" ]] && sudo rm -f /etc/rsyslog.d/indi-allsky.conf

sudo systemctl restart rsyslog


sudo cp -f ${ALLSKY_DIRECTORY}/log/logrotate_indi-allsky /etc/logrotate.d/indi-allsky
sudo chown root:root /etc/logrotate.d/indi-allsky
sudo chmod 644 /etc/logrotate.d/indi-allsky


echo "**** Indi-allsky config ****"
[[ ! -d "$ALLSKY_ETC" ]] && sudo mkdir "$ALLSKY_ETC"
sudo chown "$USER":"$PGRP" "$ALLSKY_ETC"
sudo chmod 775 "${ALLSKY_ETC}"

if [[ ! -f "${ALLSKY_ETC}/config.json" ]]; then
    if [[ -f "config.json" ]]; then
        # copy current config to etc
        cp config.json "${ALLSKY_ETC}/config.json"
        sudo rm -f "${ALLSKY_DIRECTORY}/config.json"
        ln -s "${ALLSKY_ETC}/config.json" "${ALLSKY_DIRECTORY}/config.json"
    else
        # syntax check
        cat "${ALLSKY_DIRECTORY}/config.json_template" | json_pp >/dev/null

        # create new config
        cp "${ALLSKY_DIRECTORY}/config.json_template" "${ALLSKY_ETC}/config.json"
    fi
fi

sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/config.json"
sudo chmod 660 "${ALLSKY_ETC}/config.json"

# Setup Database URI in config
SQLALCHEMY_DATABASE_URI=$(jq -r '.SQLALCHEMY_DATABASE_URI' "${ALLSKY_ETC}/config.json")
if [[ "$SQLALCHEMY_DATABASE_URI" == "null" ]]; then
    TMP_CONFIG1=$(mktemp)
    jq --argjson db_uri "\"$DB_URI_DEFAULT\"" '.SQLALCHEMY_DATABASE_URI = $db_uri' "${ALLSKY_ETC}/config.json" > $TMP_CONFIG1
    cp -f "$TMP_CONFIG1" "${ALLSKY_ETC}/config.json"
    sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/config.json"
    sudo chmod 660 "${ALLSKY_ETC}/config.json"
    [[ -f "$TMP_CONFIG1" ]] && rm -f "$TMP_CONFIG1"

    # use default
    SQLALCHEMY_DATABASE_URI="$DB_URI_DEFAULT"
fi

# Detect IMAGE_FOLDER
IMAGE_FOLDER=$(jq -r '.IMAGE_FOLDER' "${ALLSKY_ETC}/config.json")
echo "Detected image folder: $IMAGE_FOLDER"


echo "**** Flask config ****"
TMP4=$(mktemp)
#if [[ ! -f "${ALLSKY_ETC}/flask.json" ]]; then
SECRET_KEY=$(${PYTHON_BIN} -c 'import secrets; print(secrets.token_hex())')
sed \
 -e "s|%SQLALCHEMY_DATABASE_URI%|$SQLALCHEMY_DATABASE_URI|g" \
 -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
 -e "s|%SECRET_KEY%|$SECRET_KEY|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 -e "s|%HTDOCS_FOLDER%|$HTDOCS_FOLDER|g" \
 -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
 -e "s|%INDISEVER_SERVICE_NAME%|$INDISEVER_SERVICE_NAME|g" \
 -e "s|%ALLSKY_SERVICE_NAME%|$ALLSKY_SERVICE_NAME|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 "${ALLSKY_DIRECTORY}/flask.json_template" > $TMP4

# syntax check
cat $TMP4 | json_pp >/dev/null

cp -f "$TMP4" "${ALLSKY_ETC}/flask.json"
#fi

sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/flask.json"
sudo chmod 660 "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP4" ]] && rm -f "$TMP4"


TMP7=$(mktemp)
cat ${ALLSKY_DIRECTORY}/service/gunicorn.conf.py > $TMP7

cp -f "$TMP7" "${ALLSKY_ETC}/gunicorn.conf.py"
chmod 644 "${ALLSKY_ETC}/gunicorn.conf.py"
[[ -f "$TMP7" ]] && rm -f "$TMP7"



if [[ "$ASTROBERRY" == "true" ]]; then
    echo "**** Disabling apache web server (Astroberry) ****"
    sudo systemctl stop apache2 || true
    sudo systemctl disable apache2 || true


    echo "**** Setup astroberry nginx ****"
    TMP3=$(mktemp)
    sed \
     -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
     -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
     -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
     -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
     -e "s|%DOCROOT_FOLDER%|$DOCROOT_FOLDER|g" \
     -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
     -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
     -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
     ${ALLSKY_DIRECTORY}/service/nginx_astroberry_ssl > $TMP3


    if [[ ! -f "${ALLSKY_ETC}/nginx.passwd" ]]; then
        # nginx does not like bcrypt
        sudo htpasswd -cbm "${ALLSKY_ETC}/nginx.passwd" admin secret
    fi

    sudo chmod 664 "${ALLSKY_ETC}/nginx.passwd"
    sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/nginx.passwd"


    #sudo cp -f /etc/nginx/sites-available/astroberry_ssl "/etc/nginx/sites-available/astroberry_ssl_$(date +%Y%m%d_%H%M%S)"
    sudo cp -f "$TMP3" /etc/nginx/sites-available/indi-allsky_ssl
    sudo chown root:root /etc/nginx/sites-available/indi-allsky_ssl
    sudo chmod 644 /etc/nginx/sites-available/indi-allsky_ssl
    sudo ln -s -f /etc/nginx/sites-available/indi-allsky_ssl /etc/nginx/sites-enabled/indi-allsky_ssl

    sudo systemctl enable nginx
    sudo systemctl restart nginx

else
    if systemctl -q is-active nginx; then
        echo "!!! WARNING - nginx is active - This might interfere with apache !!!"
        sleep 3
    fi

    if systemctl -q is-active lighttpd; then
        echo "!!! WARNING - lighttpd is active - This might interfere with apache !!!"
        sleep 3
    fi

    echo "**** Start apache2 service ****"
    TMP3=$(mktemp)
    sed \
     -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
     -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
     -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
     -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
     -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
     -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
     -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
     ${ALLSKY_DIRECTORY}/service/apache_indi-allsky.conf > $TMP3


    if [[ ! -f "${ALLSKY_ETC}/apache.passwd" ]]; then
        sudo htpasswd -cbB "${ALLSKY_ETC}/apache.passwd" admin secret
    fi

    sudo chmod 664 "${ALLSKY_ETC}/apache.passwd"
    sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/apache.passwd"


    if [[ "$DEBIAN_DISTRO" -eq 1 ]]; then
        sudo cp -f "$TMP3" /etc/apache2/sites-available/indi-allsky.conf
        sudo chown root:root /etc/apache2/sites-available/indi-allsky.conf
        sudo chmod 644 /etc/apache2/sites-available/indi-allsky.conf


        if [[ ! -d "/etc/apache2/ssl" ]]; then
            sudo mkdir /etc/apache2/ssl
        fi

        sudo chown root:root /etc/apache2/ssl
        sudo chmod 755 /etc/apache2/ssl


        if [[ ! -f "/etc/apache2/ssl/indi-allsky_apache.key" || ! -f "/etc/apache2/ssl/indi-allsky_apache.pem" ]]; then
            sudo rm -f /etc/apache2/ssl/indi-allsky_apache.key
            sudo rm -f /etc/apache2/ssl/indi-allsky_apache.pem

            SHORT_HOSTNAME=$(hostname -s)
            KEY_TMP=$(mktemp)
            CRT_TMP=$(mktemp)

            # sudo has problems with process substitution <()
            openssl req \
                -new \
                -newkey rsa:4096 \
                -sha512 \
                -days 3650 \
                -nodes \
                -x509 \
                -subj "/CN=${SHORT_HOSTNAME}.local" \
                -keyout "$KEY_TMP" \
                -out "$CRT_TMP" \
                -extensions san \
                -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

                sudo cp -f "$KEY_TMP" /etc/apache2/ssl/indi-allsky_apache.key
                sudo cp -f "$CRT_TMP" /etc/apache2/ssl/indi-allsky_apache.pem

                rm -f "$KEY_TMP"
                rm -f "$CRT_TMP"
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
        sudo a2enmod proxy
        sudo a2enmod proxy_http
        sudo a2dissite 000-default
        sudo a2dissite default-ssl
        sudo a2ensite indi-allsky

        if [[ ! -f "/etc/apache2/ports.conf_pre_indiallsky" ]]; then
            sudo cp /etc/apache2/ports.conf /etc/apache2/ports.conf_pre_indiallsky

            # Comment out the Listen directives
            TMP9=$(mktemp)
            sed \
             -e 's|^\(.*\)[^#]\?\(listen.*\)|\1#\2|i' \
             /etc/apache2/ports.conf_pre_indiallsky > $TMP9

            sudo cp -f "$TMP9" /etc/apache2/ports.conf
            sudo chown root:root /etc/apache2/ports.conf
            sudo chmod 644 /etc/apache2/ports.conf
            [[ -f "$TMP9" ]] && rm -f "$TMP9"
        fi

        sudo systemctl enable apache2
        sudo systemctl restart apache2

    elif [[ "$REDHAT_DISTRO" -eq 1 ]]; then
        sudo cp -f "$TMP3" /etc/httpd/conf.d/indi-allsky.conf
        sudo chown root:root /etc/httpd/conf.d/indi-allsky.conf
        sudo chmod 644 /etc/httpd/conf.d/indi-allsky.conf

        sudo systemctl enable httpd
        sudo systemctl restart httpd
    fi

fi

[[ -f "$TMP3" ]] && rm -f "$TMP3"


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

for F in $IMAGE_FOLDER_FILES; do
    cp -f "${ALLSKY_DIRECTORY}/html/images/${F}" "${IMAGE_FOLDER}/${F}"
    chmod 664 "${IMAGE_FOLDER}/${F}"
done


echo "**** Setup DB ****"
[[ ! -d "$DB_FOLDER" ]] && sudo mkdir "$DB_FOLDER"
sudo chmod 775 "$DB_FOLDER"
sudo chown "$USER":"$PGRP" "$DB_FOLDER"
[[ ! -d "${DB_FOLDER}/backup" ]] && sudo mkdir "${DB_FOLDER}/backup"
sudo chmod 775 "$DB_FOLDER/backup"
sudo chown "$USER":"$PGRP" "${DB_FOLDER}/backup"
if [[ -f "${DB_FILE}" ]]; then
    sudo chmod 664 "${DB_FILE}"
    sudo chown "$USER":"$PGRP" "${DB_FILE}"

    echo "**** Backup DB prior to migration ****"
    DB_BACKUP="${DB_FOLDER}/backup/backup_$(date +%Y%m%d_%H%M%S).sql"
    sqlite3 "${DB_FILE}" .dump > "$DB_BACKUP"
    gzip "$DB_BACKUP"
fi


# Check for old alembic folder
if [[ -d "${ALLSKY_DIRECTORY}/alembic" ]]; then
    echo
    echo "You appear to have upgraded from a previous version of indi-allsky that used alembic"
    echo "for database migrations"
    echo
    echo "This script will attempt to properly migrate the config"
    echo
    sleep 5

    sqlite3 "${DB_FILE}" "DELETE FROM alembic_version;"

    rm -fR "${ALLSKY_DIRECTORY}/alembic"
fi


# Setup migration folder
if [[ ! -d "${DB_FOLDER}/migrations" ]]; then
    # Folder defined in flask config
    flask db init

    # Move migrations out of git checkout
    cd "${ALLSKY_DIRECTORY}/migrations/versions"
    find . -type f -name "*.py" | cpio -pdmu "${DB_FOLDER}/migrations/versions"
    cd "$OLDPWD"

    # Cleanup old files
    find "${ALLSKY_DIRECTORY}/migrations/versions" -type f -name "*.py" -exec rm -f {} \;
fi


flask db revision --autogenerate
flask db upgrade head


sudo chmod 664 "${DB_FILE}"
sudo chown "$USER":"$PGRP" "${DB_FILE}"


if [ "$CCD_DRIVER" == "indi_rpicam" ]; then
    echo "**** Enable Raspberry Pi camera interface ****"
    sudo raspi-config nonint do_camera 0

    echo "**** Ensure user is a member of the video group ****"
    sudo usermod -a -G video "$USER"

    echo "**** Disable star eater algorithm ****"
    sudo vcdbg set imx477_dpc 0 || true

    echo "**** Setup disable cronjob at /etc/cron.d/disable_star_eater ****"
    echo "@reboot root /usr/bin/vcdbg set imx477_dpc 0 >/dev/null 2>&1" | sudo tee /etc/cron.d/disable_star_eater
    sudo chown root:root /etc/cron.d/disable_star_eater
    sudo chmod 644 /etc/cron.d/disable_star_eater

    echo
    echo
    echo "If this is the first time you have setup your Raspberry PI camera, please reboot when"
    echo "this script completes to enable the camera interface..."
    echo
    echo

    sleep 5
fi


if [ "$CAMERA_INTERFACE" == "libcamera_imx477" ]; then
    echo "**** Enable Raspberry Pi camera interface ****"
    sudo raspi-config nonint do_camera 0

    echo "**** Ensure user is a member of the video group ****"
    sudo usermod -a -G video "$USER"

    echo "**** Disable star eater algorithm ****"
    echo "options imx477 dpc_enable=0" | sudo tee /etc/modprobe.d/imx477_dpc.conf
    sudo chown root:root /etc/modprobe.d/imx477_dpc.conf
    sudo chmod 644 /etc/modprobe.d/imx477_dpc.conf


    LIBCAMERA_CAMERAS="
        imx290
        imx378
        imx477
        imx477_noir
        imx519
    "

    for LIBCAMERA_JSON in $LIBCAMERA_CAMERAS; do
        JSON_FILE="/usr/share/libcamera/ipa/raspberrypi/${LIBCAMERA_JSON}.json"

        if [ -f "$JSON_FILE" ]; then
            echo "Disabling dpc in $JSON_FILE"

            TMP_JSON=$(mktemp)
            jq --argjson rpidpc_strength "$DPC_STRENGTH" '."rpi.dpc".strength = $rpidpc_strength' "$JSON_FILE" > $TMP_JSON
            sudo cp -f "$TMP_JSON" "$JSON_FILE"
            sudo chown root:root "$JSON_FILE"
            sudo chmod 644 "$JSON_FILE"
            [[ -f "$TMP_JSON" ]] && rm -f "$TMP_JSON"
        fi
    done


    echo
    echo
    echo "If this is the first time you have setup your Raspberry PI camera, please reboot when"
    echo "this script completes to enable the camera interface..."
    echo
    echo

    sleep 5
fi


# Disable raw frames with libcamera when running 1GB of memory
MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk {'print $2'})
if [ "$MEM_TOTAL" -lt "1536000" ]; then
    TMP_LIBCAM_TYPE=$(mktemp)
    jq --arg libcamera_file_type "jpg" '.LIBCAMERA.IMAGE_FILE_TYPE = $libcamera_file_type' "${ALLSKY_ETC}/config.json" > $TMP_LIBCAM_TYPE
    cp -f "$TMP_LIBCAM_TYPE" "${ALLSKY_ETC}/config.json"
    [[ -f "$TMP_LIBCAM_TYPE" ]] && rm -f "$TMP_LIBCAM_TYPE"
fi



echo "**** Disabling Thomas Jacquin's allsky (ignore errors) ****"
# Not trying to push out the competition, these just cannot run at the same time :-)
sudo systemctl stop allsky || true
sudo systemctl disable allsky || true


echo "**** Starting ${GUNICORN_SERVICE_NAME}.socket"
# this needs to happen after creating the $DB_FOLDER
systemctl --user start ${GUNICORN_SERVICE_NAME}.socket


echo "**** Update config camera interface ****"
TMP_CAMERA_INT=$(mktemp)
jq --arg camera_interface "$CAMERA_INTERFACE" '.CAMERA_INTERFACE = $camera_interface' "${ALLSKY_ETC}/config.json" > $TMP_CAMERA_INT
cp -f "$TMP_CAMERA_INT" "${ALLSKY_ETC}/config.json"
[[ -f "$TMP_CAMERA_INT" ]] && rm -f "$TMP_CAMERA_INT"


echo "**** Update config version ****"
TMP_CONFIG2=$(mktemp)
jq --argjson version "$INDI_ALLSKY_VERSION" '.VERSION = $version' "${ALLSKY_ETC}/config.json" > $TMP_CONFIG2
cp -f "$TMP_CONFIG2" "${ALLSKY_ETC}/config.json"
[[ -f "$TMP_CONFIG2" ]] && rm -f "$TMP_CONFIG2"


sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/config.json"
sudo chmod 660 "${ALLSKY_ETC}/config.json"



# final config syntax check
cat "${ALLSKY_ETC}/config.json" | json_pp >/dev/null
cat "${ALLSKY_ETC}/flask.json" | json_pp >/dev/null


echo
echo
echo
echo
echo "A configuration file has automatically been provisioned at /etc/indi-allsky/config.json"
echo
echo "Services can be started at the command line or can be started from the web interface"
echo
echo "    systemctl --user start indiserver"
echo "    systemctl --user start indi-allsky"
echo
echo
echo "The web interface may be accessed with the following URL"
echo " (You may have to manually access by IP)"
echo

if [[ "$HTTPS_PORT" -eq 443 ]]; then
    echo "    https://$(hostname -s).local/indi-allsky/"
    echo
    echo "    https://$(hostname -s).local/indi-allsky/public  (unauthenticated access)"
else
    echo "    https://$(hostname -s).local:$HTTPS_PORT/indi-allsky/"
    echo
    echo "    https://$(hostname -s).local:$HTTPS_PORT/indi-allsky/public  (unauthenticated access)"

fi

END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo

echo
echo "Enjoy!"
