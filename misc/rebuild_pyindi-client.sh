#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset

PATH=/bin:/usr/bin
export PATH


if [[ "$(id -u)" == "0" ]]; then
    echo
    echo "Please do not run $(basename $0) as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi

if [[ -n "$VIRTUAL_ENV" ]]; then
    echo
    echo "Please do not run $(basename $0) with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
    echo
    echo
    exit 1
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname $0)
cd "$SCRIPT_DIR/.."
ALLSKY_DIRECTORY=$PWD
cd $OLDPWD


if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky" ]; then
    echo
    echo "indi-allsky virtualenv not found, please run setup.sh"
    echo
    echo
    exit 1
fi


echo
echo
echo "The purpose of this script is to rebuild pyindi-client against"
echo " newer indilib packages."
echo
echo "Rebuild proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


source ${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate
pip3 uninstall -y pyindi-client
pip3 install --no-binary :all: --upgrade 'git+https://github.com/indilib/pyindi-client.git@d5dbe80#egg=pyindi-client'

