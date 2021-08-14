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
HTDOCS_FOLDER="/var/www/html"
IMAGE_FOLDER="${HTDOCS_FOLDER}/images"
#### end config ####


HTDOCS_FILES="
    images/js_latest.php
    images/latest.html
    images/loop.html
    images/loop_realtime.html
    images/settings_latest.js
    images/settings_loop.js
"

DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)

# get list of drivers
cd $INDI_DRIVER_PATH
INDI_DRIVERS=$(ls indi_*_ccd)
cd $OLDPWD


# Run sudo to ask for initial password
sudo true

echo "Installing packages..."
if [[ $DISTRO_NAME == "Raspbian" && $DISTRO_RELEASE == "10" ]]; then
    RSYSLOG_USER=root
    RSYSLOG_GROUP=adm

    # Astroberry repository
    if [ ! -f /etc/apt/sources.list.d/astroberry.list ]; then
        echo "Installing INDI via Astroberry repository"
        wget -O - https://www.astroberry.io/repo/key | sudo apt-key add -
        sudo su -c "echo 'deb https://www.astroberry.io/repo/ buster main' > /etc/apt/sources.list.d/astroberry.list"
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
        swig \
        libatlas-base-dev \
        libilmbase-dev \
        libopenexr-dev \
        libgtk-3-0 \
        libcurl4-gnutls-dev \
        libcfitsio-dev \
        libnova-dev \
        ffmpeg \
        libindi-dev
else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE"
    exit 1
fi


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
 -e "s|%INDISERVER_USER%|$USER|" \
 -e "s|%INDI_CCD_DRIVER%|$CCD_DRIVER|" ${ALLSKY_DIRECTORY}/service/indiserver.service > $TMP1


sudo cp -f $TMP1 /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
sudo chown root:root /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
sudo chmod 644 /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
[[ -f "$TMP1" ]] && rm -f "$TMP1"


echo "Setting up indi-allsky service"
TMP2=$(tempfile)
sed \
 -e "s|%ALLSKY_USER%|$USER|" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|" ${ALLSKY_DIRECTORY}/service/indi-allsky.service > $TMP2

sudo cp -f $TMP2 /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
sudo chown root:root /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
sudo chmod 644 /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
[[ -f "$TMP2" ]] && rm -f "$TMP2"


echo "Enabling services"
sudo systemctl daemon-reload
sudo systemctl enable $INDISEVER_SERVICE_NAME
sudo systemctl enable $ALLSKY_SERVICE_NAME


echo "Setup rsyslog logging"
sudo touch /var/log/indi-allsky.log
sudo chmod 644 /var/log/indi-allsky.log
sudo chown $RSYSLOG_USER:$RSYSLOG_GROUP /var/log/indi-allsky.log
sudo cp ${ALLSKY_DIRECTORY}/log/rsyslog_indi-allsky.conf /etc/rsyslog.d
sudo systemctl restart rsyslog


echo "Setup image folder"
[[ ! -d "$IMAGE_FOLDER" ]] && sudo mkdir -m 755 "$IMAGE_FOLDER"
sudo chown $USER "$IMAGE_FOLDER"

for F in $HTDOCS_FILES; do
    # ask to overwrite if they already exist
    cp -i $F "${HTDOCS_FOLDER}/$F"
done


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
