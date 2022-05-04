#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset

PATH=/bin:/usr/bin
export PATH


function handler_SIGINT() {
    #stty echo
    echo "Caught SIGINT, quitting"
    exit 1
}
trap handler_SIGINT SIGINT


DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)


echo "######################################################"
echo "### Welcome to the indi-allsky indi compile script ###"
echo "######################################################"


if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run $(basename $0) as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi

echo
echo
echo "Distribution: $DISTRO_NAME"
echo "Release: $DISTRO_RELEASE"
echo "Arch: $CPU_ARCH"
echo

echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10



# find script directory for service setup
SCRIPT_DIR=$(dirname $0)
cd "${SCRIPT_DIR}/.."
ALLSKY_DIRECTORY=$PWD
cd $OLDPWD



# Run sudo to ask for initial password
sudo true



echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        python3-apt \
        virtualenv \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        python3-apt \
        virtualenv \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        python3-apt \
        virtualenv \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        python3-apt \
        virtualenv \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "22.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        python3-apt \
        virtualenv \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        python3-apt \
        virtualenv \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "18.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        python3-apt \
        virtualenv \
        libffi-dev

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


echo "**** Python virtualenv setup ****"
[[ ! -d "${ALLSKY_DIRECTORY}/virtualenv" ]] && mkdir "${ALLSKY_DIRECTORY}/virtualenv"
chmod 775 "${ALLSKY_DIRECTORY}/virtualenv"
if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/ansible" ]; then
    virtualenv -p python3 --system-site-packages ${ALLSKY_DIRECTORY}/virtualenv/ansible
fi
source ${ALLSKY_DIRECTORY}/virtualenv/ansible/bin/activate
pip3 install --upgrade pip setuptools wheel
pip3 install -r ${ALLSKY_DIRECTORY}/ansible/requirements.txt


echo
echo
echo "The \"BECOME\" password is your sudo password"
echo

cd ${ALLSKY_DIRECTORY}/ansible

ansible-playbook -i inventory.yml site.yml --ask-become-pass $@

