#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset

PATH=/bin:/usr/bin
export PATH


#### config ####
INDI_DRIVER_PATH=/usr/bin
INDISEVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"
ALLSKY_ETC="/etc/indi-allsky"
HTDOCS_FOLDER="/var/www/html/allsky"
DB_FOLDER="/var/lib/indi-allsky"
#### end config ####


HTDOCS_FILES="
    latest.html
    latestDb.html
    loop.html
    loop_realtime.html
    sqm.html
    chart.html
    js/js_loop.php
    js/js_chart.php
    js/settings_latest.js
    js/settings_latestDb.js
    js/settings_loop.js
    .htaccess
    images/.htaccess
    images/darks/.htaccess
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
    echo
    echo
    echo "Detected a custom installation of INDI in /usr/local/bin"
    echo "The setup script might fail"
    echo
    echo
    sleep 3
fi


echo
echo
echo "Distribution: $DISTRO_NAME"
echo "Release: $DISTRO_RELEASE"
echo
echo "INDI_DRIVER_PATH: $INDI_DRIVER_PATH"
echo "INDISERVER_SERVICE_NAME: $INDISEVER_SERVICE_NAME"
echo "ALLSKY_SERVICE_NAME: $ALLSKY_SERVICE_NAME"
echo "GUNICORN_SERVICE_NAME: $GUNICORN_SERVICE_NAME"
echo "ALLSKY_ETC: $ALLSKY_ETC"
echo "HTDOCS_FOLDER: $HTDOCS_FOLDER"
echo "DB_FOLDER: $DB_FOLDER"
echo
echo

if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run setup.sh as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi

echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10




# Run sudo to ask for initial password
sudo true

echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    if [[ "$CPU_ARCH" == "armv7l" || "$CPU_ARCH" == "armv6l" ]]; then
        echo
        echo
        echo "Raspbian 11 is not yet support in the Astroberry repo"
        echo
        echo
        exit 1

        # Astroberry repository
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" && ! -f "/etc/apt/sources.list.d/astroberry.list" ]]; then
            echo "Installing INDI via Astroberry repository"
            wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
            sudo su -c "echo 'deb https://www.astroberry.io/repo/ bullseye main' > /etc/apt/sources.list.d/astroberry.list"
        fi
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-pip \
        python3-dbus \
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        php-sqlite3 \
        libgnutls28-dev \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        ffmpeg \
        gifsicle \
        sqlite3 \
        indi-full \
        indi-rpicam \
        libindi-dev

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data


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
        python3-pip \
        python3-dbus \
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        php-sqlite3 \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        ffmpeg \
        gifsicle \
        sqlite3 \
        indi-full \
        indi-rpicam \
        libindi-dev

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data


    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    if [[ "$CPU_ARCH" == "x86_64" ]]; then
        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            ### Install INDI from Debian testing distro (bookworm)
            echo 'APT::Default-Release "bullseye";' | sudo tee /etc/apt/apt.conf.d/99defaultrelease

            echo "deb     http://ftp.us.debian.org/debian/    bookworm main contrib non-free" | sudo tee /etc/apt/sources.list.d/bookworm.list
            echo "#deb-src http://ftp.us.debian.org/debian/    bookworm main contrib non-free" | sudo tee -a /etc/apt/sources.list.d/bookworm.list
            echo "deb     http://security.debian.org/         bookworm-security main contrib non-free" | sudo tee -a /etc/apt/sources.list.d/bookworm.list
        fi
    fi


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-pip \
        python3-dbus \
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        php-sqlite3 \
        libgnutls28-dev \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        ffmpeg \
        gifsicle \
        sqlite3

     ### Install INDI from Debian testing distro (bookworm)
     sudo apt-get -y install -t bookworm \
        indi-bin \
        libindi-dev

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data

    # need to find an indi repo

    # reconfigure system timezone
    sudo dpkg-reconfigure tzdata


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-pip \
        python3-dbus \
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        php-sqlite3 \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        ffmpeg \
        gifsicle \
        sqlite3 \
        indi-full \
        libindi-dev

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data


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
        python3 \
        python3-pip \
        python3-dbus \
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        php-sqlite3 \
        libgnutls28-dev \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        ffmpeg \
        gifsicle \
        sqlite3 \
        indi-full \
        libindi-dev

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "18.04" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=syslog
    RSYSLOG_GROUP=adm
    APACHE_USER=www-data
    APACHE_GROUP=www-data


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
        python3 \
        python3-pip \
        python3-dbus \
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        php-sqlite3 \
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        zlib1g-dev \
        libgnutls28-dev \
        ffmpeg \
        gifsicle \
        sqlite3 \
        indi-full \
        libindi-dev

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


# get list of drivers
cd $INDI_DRIVER_PATH
INDI_DRIVERS=$(ls indi_*_ccd indi_rpicam 2>/dev/null || true)
cd $OLDPWD


# find script directory for service setup
SCRIPT_DIR=$(dirname $0)
cd "$SCRIPT_DIR"
ALLSKY_DIRECTORY=$PWD
cd $OLDPWD



echo "**** Python virtualenv setup ****"
[[ ! -d "${ALLSKY_DIRECTORY}/virtualenv" ]] && mkdir -m 755 "${ALLSKY_DIRECTORY}/virtualenv"
if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky" ]; then
    virtualenv -p python3 --system-site-packages ${ALLSKY_DIRECTORY}/virtualenv/indi-allsky
fi
source ${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate
pip3 install --upgrade pip
pip3 uninstall -y opencv-python  # replaced package with opencv-python-headless
pip3 install -r requirements.txt


PS3="Select an INDI driver: "
select indi_driver_path in $INDI_DRIVERS; do
    if [ -f "${INDI_DRIVER_PATH}/${indi_driver_path}" ]; then
        CCD_DRIVER=$indi_driver_path
        break
    fi
done

#echo $CCD_DRIVER

echo "**** Remove old services ****"
sudo systemctl stop ${INDISEVER_SERVICE_NAME}.service || true
sudo systemctl stop ${ALLSKY_SERVICE_NAME}.service || true
sudo systemctl stop ${GUNICORN_SERVICE_NAME}.socket || true
sudo systemctl stop ${GUNICORN_SERVICE_NAME}.service || true
sudo systemctl disable ${INDISEVER_SERVICE_NAME}.service || true
sudo systemctl disable ${ALLSKY_SERVICE_NAME}.service || true
sudo systemctl disable ${GUNICORN_SERVICE_NAME}.socket || true
sudo systemctl disable ${GUNICORN_SERVICE_NAME}.service || true

[[ -f "/etc/systemd/system/${INDISEVER_SERVICE_NAME}.service" ]] && sudo rm -f "/etc/systemd/system/${INDISEVER_SERVICE_NAME}.service"
[[ -f "/etc/systemd/system/${ALLSKY_SERVICE_NAME}.service" ]] && sudo rm -f "/etc/systemd/system/${ALLSKY_SERVICE_NAME}.service" 
[[ -f "/etc/systemd/system/${GUNICORN_SERVICE_NAME}.socket" ]] && sudo rm -f "/etc/systemd/system/${GUNICORN_SERVICE_NAME}.socket"
[[ -f "/etc/systemd/system/${GUNICORN_SERVICE_NAME}.service" ]] && sudo rm -f "/etc/systemd/system/${GUNICORN_SERVICE_NAME}.service"

sudo systemctl daemon-reload



# create users systemd folder
[[ ! -d "${HOME}/.config/systemd/user" ]] && mkdir -p "${HOME}/.config/systemd/user"


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
systemctl --user start ${GUNICORN_SERVICE_NAME}.socket


echo "**** Ensure user is a member of the systemd-journal group ****"
sudo usermod -a -G systemd-journal "$USER"


echo "**** Setup rsyslog logging ****"
[[ ! -d "/var/log/indi-allsky" ]] && sudo mkdir -m 755 /var/log/indi-allsky
sudo touch /var/log/indi-allsky/indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/indi-allsky.log
sudo touch /var/log/indi-allsky/webapp-indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/webapp-indi-allsky.log
sudo chown -R $RSYSLOG_USER:$RSYSLOG_GROUP /var/log/indi-allsky

sudo cp -f ${ALLSKY_DIRECTORY}/log/rsyslog_indi-allsky.conf /etc/rsyslog.d/indi-allsky.conf
sudo chown root:root /etc/rsyslog.d/indi-allsky.conf
sudo chmod 644 /etc/rsyslog.d/indi-allsky.conf
sudo systemctl restart rsyslog

sudo cp -f ${ALLSKY_DIRECTORY}/log/logrotate_indi-allsky /etc/logrotate.d/indi-allsky
sudo chown root:root /etc/logrotate.d/indi-allsky
sudo chmod 644 /etc/logrotate.d/indi-allsky


echo "**** Indi-allsky config ****"
[[ ! -d "$ALLSKY_ETC" ]] && sudo mkdir -m 755 "$ALLSKY_ETC"
sudo chown "$USER":"$PGRP" "$ALLSKY_ETC"
sudo chmod 755 "${ALLSKY_ETC}"

if [[ ! -f "${ALLSKY_ETC}/config.json" ]]; then
    if [[ -f "config.json" ]]; then
        # copy current config to etc
        cp config.json "${ALLSKY_ETC}/config.json"
        sudo rm -f config.json
        ln -s "${ALLSKY_ETC}/config.json" config.json
    else
        # syntax check
        cat config.json_template | json_pp >/dev/null

        # create new config
        cp config.json_template "${ALLSKY_ETC}/config.json"
    fi
fi

sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/config.json"
sudo chmod 640 "${ALLSKY_ETC}/config.json"


echo "**** Flask config ****"
TMP4=$(mktemp)
#if [[ ! -f "${ALLSKY_ETC}/flask.json" ]]; then
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex())')
sed \
 -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
 -e "s|%SECRET_KEY%|$SECRET_KEY|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 -e "s|%HTDOCS_FOLDER%|$HTDOCS_FOLDER|g" \
 -e "s|%INDISEVER_SERVICE_NAME%|$INDISEVER_SERVICE_NAME|g" \
 -e "s|%ALLSKY_SERVICE_NAME%|$ALLSKY_SERVICE_NAME|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 flask.json_template > $TMP4

# syntax check
cat $TMP4 | json_pp >/dev/null

cp -f "$TMP4" "${ALLSKY_ETC}/flask.json"
#fi

sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/flask.json"
sudo chmod 640 "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP4" ]] && rm -f "$TMP4"


echo "**** Disabling competing web servers ****"
sudo systemctl stop nginx || true
sudo systemctl disable nnginx || true
sudo systemctl stop lighttpd || true
sudo systemctl disable lighttpd || true


echo "**** Start apache2 service ****"
TMP3=$(mktemp)
sed \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 ${ALLSKY_DIRECTORY}/service/apache_indi-allsky.conf > $TMP3


if [[ ! -f "${ALLSKY_ETC}/apache.passwd" ]]; then
    sudo htpasswd -cbB "${ALLSKY_ETC}/apache.passwd" admin secret
fi

sudo chmod 644 "${ALLSKY_ETC}/apache.passwd"
sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/apache.passwd"


if [[ "$DEBIAN_DISTRO" -eq 1 ]]; then
    sudo cp -f "$TMP3" /etc/apache2/sites-available/indi-allsky.conf
    sudo chown root:root /etc/apache2/sites-available/indi-allsky.conf
    sudo chmod 644 /etc/apache2/sites-available/indi-allsky.conf

    sudo a2enmod rewrite
    sudo a2enmod headers
    sudo a2enmod ssl
    sudo a2enmod proxy
    sudo a2enmod proxy_http
    sudo a2dissite 000-default
    sudo a2dissite default-ssl
    sudo a2ensite indi-allsky
    sudo systemctl enable apache2
    sudo systemctl restart apache2
elif [[ "$REDHAT_DISTRO" -eq 1 ]]; then
    sudo cp -f "$TMP3" /etc/httpd/conf.d/indi-allsky.conf
    sudo chown root:root /etc/httpd/conf.d/indi-allsky.conf
    sudo chmod 644 /etc/httpd/conf.d/indi-allsky.conf

    sudo systemctl enable httpd
    sudo systemctl restart httpd
fi

[[ -f "$TMP3" ]] && rm -f "$TMP3"



echo "**** Setup image folder ****"
[[ ! -d "$HTDOCS_FOLDER" ]] && sudo mkdir -m 755 "$HTDOCS_FOLDER"
sudo chown -R "$USER":"$PGRP" "$HTDOCS_FOLDER"

[[ ! -d "$HTDOCS_FOLDER/images" ]] && mkdir -m 755 "$HTDOCS_FOLDER/images"
[[ ! -d "$HTDOCS_FOLDER/images/darks" ]] && mkdir -m 755 "$HTDOCS_FOLDER/images/darks"
[[ ! -d "$HTDOCS_FOLDER/js" ]] && mkdir -m 755 "$HTDOCS_FOLDER/js"

for F in $HTDOCS_FILES; do
    # ask to overwrite if they already exist
    cp -f "${ALLSKY_DIRECTORY}/html/${F}" "${HTDOCS_FOLDER}/${F}"
    chmod 644 "${HTDOCS_FOLDER}/${F}"
done


echo "**** Setup DB ****"
[[ ! -d "$DB_FOLDER" ]] && sudo mkdir -m 755 "$DB_FOLDER"
[[ -d "$DB_FOLDER" ]] && sudo chmod ugo+rx "$DB_FOLDER"
[[ ! -d "${DB_FOLDER}/backup" ]] && sudo mkdir -m 755 "${DB_FOLDER}/backup"
sudo chown -R "$USER":"$PGRP" "$DB_FOLDER"
if [[ -f "${DB_FOLDER}/indi-allsky.sqlite" ]]; then
    sudo chmod ugo+r "$DB_FOLDER/indi-allsky.sqlite"

    echo "**** Backup DB prior to migration ****"
    DB_BACKUP="${DB_FOLDER}/backup/backup_$(date +%Y%m%d_%H%M%S).sql"
    sqlite3 "${DB_FOLDER}/indi-allsky.sqlite" .dump > $DB_BACKUP
    gzip $DB_BACKUP
fi


# Check for old alembic folder
if [[ -d "alembic" ]]; then
    echo
    echo "You appear to have upgraded from a previous version of indi-allsky that used alembic"
    echo "for database migrations"
    echo
    echo "This script will attempt to properly migrate the config"
    echo
    sleep 5

    sqlite3 ${DB_FOLDER}/indi-allsky.sqlite "DELETE FROM alembic_version;"

    rm -fR alembic
fi

flask db revision --autogenerate
flask db upgrade head


if [ "$CCD_DRIVER" == "indi_rpicam" ]; then
    echo "**** Enable Raspberry Pi camera interface ****"
    sudo raspi-config nonint do_camera 0

    echo "**** Ensure user is a member of the video group ****"
    sudo usermod -a -G video "$USER"

    echo "**** Disable star eater algorithm ****"
    sudo vcdbg set imx477_dpc 0 || true

    echo "**** Setup disable crontjob at /etc/cron.d/disable_star_eater ****"
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


echo
echo
echo
echo
echo "Now copy a config file from the examples/ folder to config.json"
echo "Customize config.json and start the software"
echo
echo "    sudo systemctl start indiserver"
echo "    sudo systemctl start indi-allsky"
echo
echo
echo "The web interface may be accessed with the following URL"
echo " (You may have to manually access by IP)"
echo
echo "    https://$(hostname -s)/"
echo
echo "Enjoy!"
