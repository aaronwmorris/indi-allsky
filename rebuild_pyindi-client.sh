#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset

PATH=/bin:/usr/bin
export PATH


# find script directory for service setup
SCRIPT_DIR=$(dirname $0)
cd "$SCRIPT_DIR"
ALLSKY_DIRECTORY=$PWD
cd $OLDPWD


source ${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate
pip3 uninstall -y pyindi-client
pip3 install --no-binary :all: pyindi-client

