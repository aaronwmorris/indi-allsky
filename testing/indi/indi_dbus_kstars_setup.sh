#!/bin/bash

set -o errexit
set -o nounset


PATH=/usr/bin:/bin
export PATH


sudo apt-get -y install \
    build-essential
    cmake \
    python3-dev \
    pkg-config \
    libcairo2-dev \
    libgirepository1.0-dev \
    libdbus-1-dev \
    ftools-fv


echo
echo "Now install PyGObject and dbus-python in your virtualenv"
echo
