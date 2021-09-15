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
HTDOCS_FOLDER="/var/www/html/allsky"
#### end config ####


HTDOCS_FILES="
    js_latest.php
    latest.html
    loop.html
    loop_realtime.html
    sqm.html
    settings_latest.js
    settings_loop.js
    .htaccess
    images/.htaccess
    images/darks/.htaccess
"

DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)


echo "##############################################"
echo "### Welcome to the indi-allsy setup script ###"
echo "##############################################"


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
echo "HTDOCS_FOLDER: $HTDOCS_FOLDER"
echo
echo
echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10




# Run sudo to ask for initial password
sudo true

echo "Installing packages..."
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    if [[ "$CPU_ARCH" == "armv7l" ]]; then
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
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        libapache2-mod-wsgi-py3 \
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

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    DEBIAN_DISTRO=1
    REDHAT_DISTRO=0

    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    # need to find an indi repo

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-pip \
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        libapache2-mod-wsgi-py3 \
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
        virtualenv \
        git \
        apache2 \
        libapache2-mod-php \
        libapache2-mod-wsgi-py3 \
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

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


# get list of drivers
cd $INDI_DRIVER_PATH
INDI_DRIVERS=$(ls indi_*_ccd)
cd $OLDPWD


# find script directory for service setup
SCRIPT_DIR=$(dirname $0)
cd "$SCRIPT_DIR"
ALLSKY_DIRECTORY=$PWD
cd $OLDPWD



echo "Python virtualenv setup"
[[ ! -d "${ALLSKY_DIRECTORY}/virtualenv" ]] && mkdir -m 755 "${ALLSKY_DIRECTORY}/virtualenv"
if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky" ]; then
    virtualenv -p python3 ${ALLSKY_DIRECTORY}/virtualenv/indi-allsky
fi
source ${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate
pip3 install -r requirements.txt


PS3="Select an INDI driver: "
select indi_driver_path in $INDI_DRIVERS; do
    if [ -f "${INDI_DRIVER_PATH}/${indi_driver_path}" ]; then
        CCD_DRIVER=$indi_driver_path
        break
    fi
done

#echo $CCD_DRIVER

echo "Setting up indiserver service"
TMP1=$(tempfile)
sed \
 -e "s|%INDISERVER_USER%|$USER|g" \
 -e "s|%INDI_CCD_DRIVER%|$CCD_DRIVER|g" ${ALLSKY_DIRECTORY}/service/indiserver.service > $TMP1


sudo cp -f "$TMP1" /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
sudo chown root:root /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
sudo chmod 644 /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
[[ -f "$TMP1" ]] && rm -f "$TMP1"


echo "Setting up indi-allsky service"
TMP2=$(tempfile)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" ${ALLSKY_DIRECTORY}/service/indi-allsky.service > $TMP2

sudo cp -f "$TMP2" /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
sudo chown root:root /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
sudo chmod 644 /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
[[ -f "$TMP2" ]] && rm -f "$TMP2"


echo "Enabling services"
sudo systemctl daemon-reload
sudo systemctl enable $INDISEVER_SERVICE_NAME
sudo systemctl enable $ALLSKY_SERVICE_NAME


echo "Setup rsyslog logging"
[[ ! -d "/var/log/indi-allsky" ]] && sudo mkdir -m 755 /var/log/indi-allsky
sudo touch /var/log/indi-allsky/indi-allsky.log
sudo chmod 644 /var/log/indi-allsky/indi-allsky.log
sudo chown -R $RSYSLOG_USER:$RSYSLOG_GROUP /var/log/indi-allsky

sudo cp -f ${ALLSKY_DIRECTORY}/log/rsyslog_indi-allsky.conf /etc/rsyslog.d/indi-allsky.conf
sudo chown root:root /etc/rsyslog.d/indi-allsky.conf
sudo chmod 644 /etc/rsyslog.d/indi-allsky.conf
sudo systemctl restart rsyslog

sudo cp -f ${ALLSKY_DIRECTORY}/log/logrotate_indi-allsky /etc/logrotate.d/indi-allsky
sudo chown root:root /etc/logrotate.d/indi-allsky
sudo chmod 644 /etc/logrotate.d/indi-allsky



echo "Start apache2 service"

TMP3=$(tempfile)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" ${ALLSKY_DIRECTORY}/service/apache_indi-allsky.conf > $TMP3


if [[ "$DEBIAN_DISTRO" -eq 1 ]]; then
    sudo cp -f "$TMP3" /etc/apache2/sites-available/indi-allsky.conf
    sudo chown root:root /etc/apache2/sites-available/indi-allsky.conf
    sudo chmod 644 /etc/apache2/sites-available/indi-allsky.conf

    sudo a2enmod rewrite
    sudo a2enmod ssl
    sudo a2enmod wsgi
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



echo "Setup image folder"
[[ ! -d "$HTDOCS_FOLDER" ]] && sudo mkdir -m 755 "$HTDOCS_FOLDER"
sudo chown -R "$USER" "$HTDOCS_FOLDER"

[[ ! -d "$HTDOCS_FOLDER/images" ]] && mkdir -m 755 "$HTDOCS_FOLDER/images"
[[ ! -d "$HTDOCS_FOLDER/images/darks" ]] && mkdir -m 755 "$HTDOCS_FOLDER/images/darks"

for F in $HTDOCS_FILES; do
    # ask to overwrite if they already exist
    cp -i "${ALLSKY_DIRECTORY}/html/${F}" "${HTDOCS_FOLDER}/${F}"
    chmod 644 "${HTDOCS_FOLDER}/${F}"
done


echo "Setup DB"
[[ ! -d "/var/lib/indi-allsky" ]] && sudo mkdir -m 755 "/var/lib/indi-allsky"
sudo chown -R "$USER" /var/lib/indi-allsky
flask db revision --autogenerate
flask db upgrade head


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
echo "Enjoy!"
