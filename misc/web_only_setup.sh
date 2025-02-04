#!/bin/bash

#set -x  # command tracing
#set -o errexit  # replace by trapping ERR
#set -o nounset  # problems with python virtualenvs
shopt -s nullglob

PATH=/usr/bin:/bin
export PATH


#### config ####
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"
ALLSKY_SERVICE_NAME="indi-allsky"

ALLSKY_ETC="/etc/indi-allsky"
DOCROOT_FOLDER="/var/www/html"
HTDOCS_FOLDER="${DOCROOT_FOLDER}/allsky"

DB_FOLDER="/var/lib/indi-allsky"
DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"
SQLALCHEMY_DATABASE_URI="sqlite:///${DB_FILE}"
MIGRATION_FOLDER="$DB_FOLDER/migrations"

OS_PACKAGE_UPGRADE="${INDI_ALLSKY_OS_PACKAGE_UPGRADE:-}"

# mysql support is not ready
USE_MYSQL_DATABASE="${INDIALLSKY_USE_MYSQL_DATABASE:-false}"

HTTP_PORT="${INDIALLSKY_HTTP_PORT:-80}"
HTTPS_PORT="${INDIALLSKY_HTTPS_PORT:-443}"

FLASK_AUTH_ALL_VIEWS="${INDIALLSKY_FLASK_AUTH_ALL_VIEWS:-}"
WEB_USER="${INDIALLSKY_WEB_USER:-}"
WEB_PASS="${INDIALLSKY_WEB_PASS:-}"
WEB_NAME="${INDIALLSKY_WEB_NAME:-}"
WEB_EMAIL="${INDIALLSKY_WEB_EMAIL:-}"
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


echo "###################################################"
echo "### Welcome to the indi-allsky web setup script ###"
echo "###################################################"


if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo "Please do not run $(basename "$0") with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
    echo
    echo
    exit 1
fi


if systemctl --user -q is-active "${ALLSKY_SERVICE_NAME}" >/dev/null 2>&1; then
    # this would not normally happen on a web only install
    echo
    echo
    echo "WARNING: indi-allsky is running.  It is recommended to stop the service before running this script."
    echo
    sleep 5
fi


if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


if [ -n "${WHIPTAIL_BIN:-}" ]; then
    "$WHIPTAIL_BIN" \
        --title "Welcome to indi-allsky" \
        --msgbox "*** Welcome to the indi-allsky web setup script ***\n\nDistribution: $DISTRO_ID\nRelease: $DISTRO_VERSION_ID\nArch: $CPU_ARCH\nBits: $CPU_BITS\n\nCPUs: $CPU_TOTAL\nMemory: $MEM_TOTAL kB\n\nHTTP Port: $HTTP_PORT\nHTTPS Port: $HTTPS_PORT" 0 0
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
echo "GUNICORN_SERVICE_NAME: $GUNICORN_SERVICE_NAME"
echo "ALLSKY_ETC: $ALLSKY_ETC"
echo "HTDOCS_FOLDER: $HTDOCS_FOLDER"
echo "DB_FOLDER: $DB_FOLDER"
echo "DB_FILE: $DB_FILE"
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


START_TIME=$(date +%s)


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


echo "**** Installing packages... ****"
if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "raspbian" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "12" ]]; then
        RSYSLOG_USER=root
        RSYSLOG_GROUP=adm

        MYSQL_ETC="/etc/mysql"

        PYTHON_BIN=python3.11

        VIRTUALENV_REQ=requirements/requirements_latest_web.txt


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
            procps \
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
            polkitd \
            dbus-user-session


        if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
            sudo apt-get -y install \
                mariadb-server
        fi

    elif [[ "$DISTRO_VERSION_ID" == "11" ]]; then
        RSYSLOG_USER=root
        RSYSLOG_GROUP=adm

        MYSQL_ETC="/etc/mysql"

        PYTHON_BIN=python3.9

        VIRTUALENV_REQ=requirements/requirements_debian11_web.txt


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
            procps \
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
            policykit-1 \
            dbus-user-session


        if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
            sudo apt-get -y install \
                mariadb-server
        fi
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "ubuntu" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "24.04" ]]; then
        RSYSLOG_USER=syslog
        RSYSLOG_GROUP=adm

        MYSQL_ETC="/etc/mysql"

        PYTHON_BIN=python3.12

        VIRTUALENV_REQ=requirements/requirements_latest_web.txt


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
            procps \
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
            polkitd \
            dbus-user-session


        if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
            sudo apt-get -y install \
                mariadb-server
        fi

    elif [[ "$DISTRO_VERSION_ID" == "22.04" ]]; then
        RSYSLOG_USER=syslog
        RSYSLOG_GROUP=adm

        MYSQL_ETC="/etc/mysql"

        PYTHON_BIN=python3.11

        VIRTUALENV_REQ=requirements/requirements_latest_web.txt


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
            procps \
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
            policykit-1 \
            dbus-user-session


        if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
            sudo apt-get -y install \
                mariadb-server
        fi

    elif [[ "$DISTRO_VERSION_ID" == "20.04" ]]; then
        RSYSLOG_USER=syslog
        RSYSLOG_GROUP=adm

        MYSQL_ETC="/etc/mysql"

        PYTHON_BIN=python3.9

        VIRTUALENV_REQ=requirements/requirements_debian11_web.txt


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
            procps \
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
            policykit-1 \
            dbus-user-session


        if [[ "$USE_MYSQL_DATABASE" == "true" ]]; then
            sudo apt-get -y install \
                mariadb-server
        fi

    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
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
    echo "WARNING: If you use screen, tmux, or byobu for virtual sessions, this check may always fail"
    echo
    exit 1
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.." || catch_error
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


# shellcheck source=/dev/null
source "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate"

pip3 install --upgrade pip setuptools wheel packaging
pip3 install -r "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ}"


# create users systemd folder
[[ ! -d "${HOME}/.config/systemd/user" ]] && mkdir -p "${HOME}/.config/systemd/user"


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
 -e "s|%ALLSKY_USER%|$USER|g" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 "${ALLSKY_DIRECTORY}/service/gunicorn-indi-allsky.service" > "$TMP6"

cp -f "$TMP6" "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.service"
chmod 644 "${HOME}/.config/systemd/user/${GUNICORN_SERVICE_NAME}.service"
[[ -f "$TMP6" ]] && rm -f "$TMP6"


echo "**** Enabling services ****"
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload


# gunicorn service is started by the socket
systemctl --user disable ${GUNICORN_SERVICE_NAME}.service
systemctl --user enable ${GUNICORN_SERVICE_NAME}.socket


echo "**** Setup rsyslog logging ****"
[[ ! -d "/var/log/indi-allsky" ]] && sudo mkdir /var/log/indi-allsky
sudo chmod 755 /var/log/indi-allsky
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

touch "${ALLSKY_ETC}/indi-allsky.env"
chmod 600 "${ALLSKY_ETC}/indi-allsky.env"


echo "**** Flask config ****"

while [ -z "${FLASK_AUTH_ALL_VIEWS:-}" ]; do
    if whiptail --title "Web Authentication" --yesno "Do you want to require authentication for all web site views?\n\nIf \"no\", privileged actions are still protected by authentication." 0 0 --defaultno; then
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
[[ ! -d "$DB_FOLDER" ]] && sudo mkdir "$DB_FOLDER"
sudo chmod 775 "$DB_FOLDER"
sudo chown -R "$USER":"$PGRP" "$DB_FOLDER"
[[ ! -d "${DB_FOLDER}/backup" ]] && sudo mkdir "${DB_FOLDER}/backup"
sudo chmod 775 "$DB_FOLDER/backup"
sudo chown "$USER":"$PGRP" "${DB_FOLDER}/backup"
if [[ -f "${DB_FILE}" ]]; then
    sudo chmod 664 "${DB_FILE}"
    sudo chown "$USER":"$PGRP" "${DB_FILE}"

    echo "**** Backup DB prior to migration ****"
    DB_BACKUP="${DB_FOLDER}/backup/backup_$(date +%Y%m%d_%H%M%S).sql.gz"
    sqlite3 "${DB_FILE}" .dump | gzip -c > "$DB_BACKUP"

    chmod 640 "$DB_BACKUP"
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


    if [[ ! -f "$MYSQL_ETC/ssl/indi-allsky_mysql.key" || ! -f "$MYSQL_ETC/ssl/indi-allsky_mysq.pem" ]]; then
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
"${ALLSKY_DIRECTORY}/config.py" dump > "$TMP_CONFIG_DUMP"



# Detect IMAGE_FOLDER
IMAGE_FOLDER=$(jq -r '.IMAGE_FOLDER' "$TMP_CONFIG_DUMP")

echo
echo
echo "Detected IMAGE_FOLDER: $IMAGE_FOLDER"
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


# indented to match setup.sh
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
     -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
     -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
     -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
     -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
     -e "s|%UPSTREAM_SERVER%|unix:$DB_FOLDER/$GUNICORN_SERVICE_NAME.sock\|http://localhost/indi-allsky|g" \
     "${ALLSKY_DIRECTORY}/service/apache_indi-allsky.conf" > "$TMP3"


    if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "ubuntu" ]]; then
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
            APACHE_KEY_TMP=$(mktemp --suffix=.key)
            APACHE_CRT_TMP=$(mktemp --suffix=.pem)

            # sudo has problems with process substitution <()
            openssl req \
                -new \
                -newkey rsa:4096 \
                -sha512 \
                -days 3650 \
                -nodes \
                -x509 \
                -subj "/CN=${SHORT_HOSTNAME}.local" \
                -keyout "$APACHE_KEY_TMP" \
                -out "$APACHE_CRT_TMP" \
                -extensions san \
                -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

            sudo cp -f "$APACHE_KEY_TMP" /etc/apache2/ssl/indi-allsky_apache.key
            sudo cp -f "$APACHE_CRT_TMP" /etc/apache2/ssl/indi-allsky_apache.pem

            rm -f "$APACHE_KEY_TMP"
            rm -f "$APACHE_CRT_TMP"
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

        sudo systemctl enable apache2
        sudo systemctl restart apache2
    fi


[[ -f "$TMP3" ]] && rm -f "$TMP3"


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


echo "**** Starting ${GUNICORN_SERVICE_NAME}.socket"
# this needs to happen after creating the $DB_FOLDER
systemctl --user start ${GUNICORN_SERVICE_NAME}.socket


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
        WEB_EMAIL=$(whiptail --title "Full Name" --nocancel --inputbox "Please enter the users email" 0 0 3>&1 1>&2 2>&3)
    done

    "$ALLSKY_DIRECTORY/misc/usertool.py" adduser -u "$WEB_USER" -p "$WEB_PASS" -f "$WEB_NAME" -e "$WEB_EMAIL"
    "$ALLSKY_DIRECTORY/misc/usertool.py" setadmin -u "$WEB_USER"
fi


# load all changes
"${ALLSKY_DIRECTORY}/config.py" load -c "$TMP_CONFIG_DUMP" --force
[[ -f "$TMP_CONFIG_DUMP" ]] && rm -f "$TMP_CONFIG_DUMP"


# ensure latest code is active
systemctl --user restart ${GUNICORN_SERVICE_NAME}.service


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
