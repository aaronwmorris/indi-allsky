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


INDI_CORE_TAG="v2.0.0"
INDI_3RDPARTY_TAG=$INDI_CORE_TAG

DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)


echo "######################################################"
echo "### Welcome to the indi-allsky indi compile script ###"
echo "######################################################"


if [[ "$(id -u)" == "0" ]]; then
    echo
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi

if [[ -n "$VIRTUAL_ENV" ]]; then
    echo
    echo "Please do not run $(basename "$0") with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
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
echo "Indi core:     $INDI_CORE_TAG"
echo "Indi 3rdparty: $INDI_3RDPARTY_TAG"
echo

echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "${SCRIPT_DIR}/.."
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD"



# Run sudo to ask for initial password
sudo true


START_TIME=$(date +%s)


echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then
    PYTHON_BIN=python3
    VIRTUALENV_REQ=requirements.txt

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        ca-certificates \
        rustc \
        cargo \
        libapt-pkg-dev \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    PYTHON_BIN=python3
    VIRTUALENV_REQ=requirements.txt

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        ca-certificates \
        rustc \
        cargo \
        libapt-pkg-dev \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then
    PYTHON_BIN=python3
    VIRTUALENV_REQ=requirements.txt

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        ca-certificates \
        rustc \
        cargo \
        libapt-pkg-dev \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    echo
    echo
    echo "The python packages necessary for the ansible build will not complete on Debian 10"
    echo
    exit 1

    PYTHON_BIN=python3
    VIRTUALENV_REQ=requirements_debian10.txt

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        ca-certificates \
        rustc \
        cargo \
        libapt-pkg-dev \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "22.04" ]]; then
    PYTHON_BIN=python3
    VIRTUALENV_REQ=requirements.txt

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        python3 \
        python3-dev \
        python3-venv \
        python3-pip \
        virtualenv \
        ca-certificates \
        rustc \
        cargo \
        libapt-pkg-dev \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libffi-dev

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then
    PYTHON_BIN=python3.9
    VIRTUALENV_REQ=requirements.txt

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        python3.9 \
        python3.9-dev \
        python3.9-venv \
        python3-pip \
        virtualenv \
        ca-certificates \
        rustc \
        cargo \
        libapt-pkg-dev \
        libssl-dev \
        libxml2-dev \
        libxslt-dev \
        libffi-dev

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


echo "**** Python virtualenv setup ****"
[[ ! -d "${ALLSKY_DIRECTORY}/virtualenv" ]] && mkdir "${ALLSKY_DIRECTORY}/virtualenv"
chmod 775 "${ALLSKY_DIRECTORY}/virtualenv"
if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/ansible" ]; then
    virtualenv -p "${PYTHON_BIN}" "${ALLSKY_DIRECTORY}/virtualenv/ansible"
fi
# shellcheck source=/dev/null
source "${ALLSKY_DIRECTORY}/virtualenv/ansible/bin/activate"
pip3 install --upgrade pip setuptools wheel
pip3 install -r "${ALLSKY_DIRECTORY}/ansible/${VIRTUALENV_REQ}"


echo
echo
echo "The \"BECOME\" password is your sudo password"
echo

cd "${ALLSKY_DIRECTORY}/ansible"

# shellcheck disable=SC2068
ansible-playbook -i inventory.yml site.yml --ask-become-pass -e "indi_core_git_version=${INDI_CORE_TAG}" -e "indi_3rdparty_git_version=${INDI_3RDPARTY_TAG}" $@


END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo
