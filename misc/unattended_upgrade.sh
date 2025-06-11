#!/bin/bash

#set -x  # command tracing
#set -o errexit  # replace by trapping ERR
#set -o nounset  # problems with python virtualenvs
shopt -s nullglob

PATH=/usr/bin:/bin
export PATH


#### config ####
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"
UPGRADE_ALLSKY_SERVICE_NAME="upgrade-indi-allsky"

ALLSKY_ETC="/etc/indi-allsky"
DB_FOLDER="/var/lib/indi-allsky"
DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"

OPTIONAL_PYTHON_MODULES="${INDIALLSKY_OPTIONAL_PYTHON_MODULES:-true}"
GPIO_PYTHON_MODULES="${INDIALLSKY_GPIO_PYTHON_MODULES:-true}"
#### end config ####


function catch_error() {
    "$ALLSKY_DIRECTORY/misc/add_notification.py" GENERAL unattended_upgrade 'Unattended upgrade failed' 1440 || true

    echo
    echo
    echo "###############"
    echo "###  ERROR  ###"
    echo "###############"
    echo
    echo "The upgrade script exited abnormally, please try to run again..."
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
    echo "The upgrade script was interrupted, please run the script again to finish..."
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


echo "############################################################"
echo "### Welcome to the indi-allsky unattended upgrade script ###"
echo "############################################################"

echo
echo
echo "This script will pull the latest code from the indi-allsky git"
echo "repository and update the code state with no manual intervention"


if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo
    echo "Please do not run $(basename "$0") with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
    echo
    echo
    exit 1
fi


ROOT_FREE=$(df -Pk / | tail -n 1 | awk "{ print \$3 }")
if [ "$ROOT_FREE" -lt 1000000 ]; then
    echo
    echo "Not enough free space available in / (root) filesystem"
    echo "At least 1GB of space needs to be available to continue"
    exit 1
fi


VAR_FREE=$(df -Pk /var | tail -n 1 | awk "{ print \$3 }")
if [ "$VAR_FREE" -lt 1000000 ]; then
    echo
    echo "Not enough free space available in /var filesystem"
    echo "At least 1GB of space needs to be available to continue"
    exit 1
fi


if systemctl --user --quiet is-active "${ALLSKY_SERVICE_NAME}.service" >/dev/null 2>&1; then
    echo
    echo
    echo "WARNING: indi-allsky is running.  The service will be stopped during the upgrade"
    echo
    sleep 3
fi


if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
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


if systemctl --user --quiet is-enabled "${ALLSKY_SERVICE_NAME}.timer" 2>/dev/null; then
    ### make sure the timer is not started
    ### this can be left in a stopped state
    systemctl --user stop "${ALLSKY_SERVICE_NAME}.timer"
fi


if systemctl --user --quiet is-enabled "${UPGRADE_ALLSKY_SERVICE_NAME}.service" 2>/dev/null; then
    ### This service should always be disabled
    systemctl --user disable "${UPGRADE_ALLSKY_SERVICE_NAME}.service"
fi


echo "Upgrade proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "raspbian" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "13" ]]; then
        DISTRO="debian_13"
    elif [[ "$DISTRO_VERSION_ID" == "12" ]]; then
        DISTRO="debian_12"
    elif [[ "$DISTRO_VERSION_ID" == "11" ]]; then
        DISTRO="debian_11"
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


START_TIME=$(date +%s)


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.." || catch_error
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD" || catch_error


if [ ! -f "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate" ]; then
    echo
    echo "indi-allsky virtualenv does not exist"
    exit 1
fi


cd "$ALLSKY_DIRECTORY" || catch_error


ALLSKY_GIT_BRANCH=$(git branch --show-current)
if [ "$ALLSKY_GIT_BRANCH" != "main" ]; then
    echo
    echo "Not currently on main branch.  Exiting..."
    exit 1
fi


# stop indi-allsky
if systemctl --user --quiet is-active "${ALLSKY_SERVICE_NAME}.service" >/dev/null 2>&1; then
    echo "*** Stopping indi-allsky ***"
    ALLSKY_RUNNING="true"
    systemctl --user stop "${ALLSKY_SERVICE_NAME}.service"
else
    ALLSKY_RUNNING="false"
fi


echo
echo "*** Updating code from git repo ***"
git pull origin main


### These are the default requirements which may be overridden
VIRTUALENV_REQ=requirements/requirements_latest.txt
VIRTUALENV_REQ_OPT=requirements/requirements_optional.txt
VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
VIRTUALENV_REQ_GPIO=requirements/requirements_gpio.txt


if [[ "$DISTRO" == "debian_13" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_32.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi

    sudo --non-interactive apt-get update

    sudo --non-interactive apt-get -y install \
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

elif [[ "$DISTRO" == "debian_12" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_32.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi

    sudo --non-interactive apt-get update

    sudo --non-interactive apt-get -y install \
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

elif [[ "$DISTRO" == "debian_11" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
    else
        VIRTUALENV_REQ=requirements/requirements_debian11.txt
    fi


    sudo --non-interactive apt-get update

    sudo --non-interactive apt-get -y install \
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

elif [[ "$DISTRO" == "ubuntu_24.04" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_32.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi


    sudo --non-interactive apt-get update

    sudo --non-interactive apt-get -y install \
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

elif [[ "$DISTRO" == "ubuntu_22.04" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_32.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi


    sudo --non-interactive apt-get update

    sudo --non-interactive apt-get -y install \
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

elif [[ "$DISTRO" == "ubuntu_20.04" ]]; then

    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
    else
        VIRTUALENV_REQ=requirements/requirements_debian11.txt
    fi


    sudo --non-interactive apt-get update

    sudo --non-interactive apt-get -y install \
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

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
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


echo "**** Flask config ****"

TMP_FLASK=$(mktemp --suffix=.json)
TMP_FLASK_MERGE=$(mktemp --suffix=.json)


cat "${ALLSKY_DIRECTORY}/flask.json_template" > "$TMP_FLASK"


# make a backup
cp -f "${ALLSKY_ETC}/flask.json" "${ALLSKY_ETC}/flask.json_old"
chmod 640 "${ALLSKY_ETC}/flask.json_old"


# attempt to merge configs giving preference to the original config (listed 2nd)
jq -s '.[0] * .[1]' "$TMP_FLASK" "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_MERGE"
cp -f "$TMP_FLASK_MERGE" "${ALLSKY_ETC}/flask.json"

chmod 660 "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP_FLASK" ]] && rm -f "$TMP_FLASK"
[[ -f "$TMP_FLASK_MERGE" ]] && rm -f "$TMP_FLASK_MERGE"


if [[ -f "${DB_FILE}" ]]; then
    echo "**** Backup DB prior to migration ****"
    DB_BACKUP="${DB_FOLDER}/backup/backup_indi-allsky_$(date +%Y%m%d_%H%M%S).sqlite"
    sqlite3 "${DB_FILE}" ".backup ${DB_BACKUP}"
    gzip "$DB_BACKUP"

    chmod 640 "${DB_BACKUP}.gz"

    echo "**** Vacuum DB ****"
    sqlite3 "${DB_FILE}" "VACUUM;"
fi


cd "$ALLSKY_DIRECTORY" || catch_error
flask db revision --autogenerate
flask db upgrade head
cd "$OLDPWD" || catch_error


# some schema changes require data to be populated
echo "**** Populate database fields ****"
"${ALLSKY_DIRECTORY}/misc/populate_data.py"



# dump config for processing
TMP_CONFIG_DUMP=$(mktemp --suffix=.json)
"${ALLSKY_DIRECTORY}/config.py" dumpfile --outfile "$TMP_CONFIG_DUMP"


# final config syntax check
json_pp < "$TMP_CONFIG_DUMP" > /dev/null


# load all changes
"${ALLSKY_DIRECTORY}/config.py" load -c "$TMP_CONFIG_DUMP" --force
[[ -f "$TMP_CONFIG_DUMP" ]] && rm -f "$TMP_CONFIG_DUMP"


# final config syntax check
json_pp < "${ALLSKY_ETC}/flask.json" > /dev/null


# ensure latest code is active
systemctl --user restart "${GUNICORN_SERVICE_NAME}.service"


# restart indi-allsky
if [ "$ALLSKY_RUNNING" == "true" ]; then
    echo "*** Restarting indi-allsky ***"
    systemctl --user start "${ALLSKY_SERVICE_NAME}.service"
fi


"$ALLSKY_DIRECTORY/misc/add_notification.py" GENERAL unattended_upgrade 'Unattended upgrade complete' 1440 || true


END_TIME=$(date +%s)


echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo

echo
echo "Enjoy!"
