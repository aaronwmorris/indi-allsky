#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset

PATH=/bin:/usr/bin:/usr/local/bin
export PATH


#### config ####
INDI_DRIVER_PATH=/usr/bin
INDISEVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
#### end config ####



DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)

# get list of drivers
cd $INDI_DRIVER_PATH
INDI_DRIVERS=$(ls indi_*_ccd)
cd $OLDPWD


echo "Installing packages..."
if [[ $DISTRO_NAME == "Raspbian" && $DISTRO_RELEASE == "10" ]]; then
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-pip \
        virtualenv \
        git \
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
 -e "s|%INDI_CCD_DRIVER%|$CCD_DRIVER|" service/indiserver.service > $TMP1


sudo cp -f $TMP1 /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
sudo chown root:root /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
sudo chmod 644 /etc/systemd/system/${INDISEVER_SERVICE_NAME}.service
[[ -f "$TMP1" ]] && rm -f "$TMP1"


echo "Setting up indi-allsky service"
TMP2=$(tempfile)
sed \
 -e "s|%ALLSKY_USER%|$USER|" \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|" service/indi-allsky.service > $TMP2

sudo cp -f $TMP2 /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
sudo chown root:root /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
sudo chmod 644 /etc/systemd/system/${ALLSKY_SERVICE_NAME}.service
[[ -f "$TMP2" ]] && rm -f "$TMP2"


echo "Enabling services"
sudo systemctl daemon-reload
sudo systemctl enable $INDISEVER_SERVICE_NAME
sudo systemctl enable $ALLSKY_SERVICE_NAME


# cleanup
