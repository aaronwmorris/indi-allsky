#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

PATH=/bin:/usr/bin
export PATH


function handler_SIGINT() {
    #stty echo
    echo "Caught SIGINT, quitting"
    exit 1
}
trap handler_SIGINT SIGINT


if [ -n "${1:-}" ]; then
    INDI_CORE_TAG="$1"
    INDI_3RDPARTY_TAG=$INDI_CORE_TAG
else
    INDI_CORE_TAG="v2.0.0"
    INDI_3RDPARTY_TAG=$INDI_CORE_TAG
fi


DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)

PROJECTS_FOLDER="$HOME/Projects"

CMAKE_BIN=cmake
INSTALL_PREFIX="/usr/local"


# can be overridden by environment variables
#BUILD_INDI_CORE="true"
#BUILD_INDI_3RDPARTY="true"


MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk "{print \$2}")
if [ "$MEM_TOTAL" -lt "1536000" ]; then
    MAKE_CONCURRENT=1
elif [ "$MEM_TOTAL" -lt "2560000" ]; then
    MAKE_CONCURRENT=2
else
    MAKE_CONCURRENT=$(nproc)
fi


if pkg-config --modversion libindi >/dev/null 2>&1; then
    DETECTED_INDIVERSION=$(pkg-config --modversion libindi)
fi


echo "######################################################"
echo "### Welcome to the indi-allsky indi compile script ###"
echo "######################################################"


# sanity check
if [[ "$(id -u)" == "0" ]]; then
    echo
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


if [ -f "/usr/bin/indiserver" ]; then
    echo
    echo
    echo "Detected indiserver installed in /usr/bin... quitting"
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
echo "Existing INDI: ${DETECTED_INDIVERSION:-none}"
echo
echo "BUILD_INDI_CORE: ${BUILD_INDI_CORE:-true}"
echo "BUILD_INDI_3RDPARTY: ${BUILD_INDI_3RDPARTY:-true}"
echo
echo "Running make with $MAKE_CONCURRENT processes"
echo

echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


START_TIME=$(date +%s)


echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then
    BLOCKING_PACKAGES="indi-full libindi-data libindi-dev libindi-plugins"
    for p in $BLOCKING_PACKAGES; do
        if dpkg -s "$p" >/dev/null 2>&1; then
            echo
            echo
            echo "Package $p needs to be uninstalled"
            echo
            exit 1
        fi
    done

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        ca-certificates \
        cmake \
        fxload \
        pkg-config \
        libavcodec-dev \
        libavdevice-dev \
        libboost-dev \
        libboost-regex-dev \
        libcfitsio-dev \
        libcurl4-gnutls-dev \
        libdc1394-22-dev \
        libev-dev \
        libfftw3-dev \
        libftdi1-dev \
        libftdi-dev \
        libgmock-dev \
        libgphoto2-dev \
        libgps-dev \
        libgsl-dev \
        libjpeg-dev \
        liblimesuite-dev \
        libnova-dev \
        libraw-dev \
        librtlsdr-dev \
        libtheora-dev \
        libtiff-dev \
        libusb-1.0-0-dev \
        zlib1g-dev

        #libnutclient-dev \

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    BLOCKING_PACKAGES="indi-full libindi-data libindi-dev libindi-plugins"
    for p in $BLOCKING_PACKAGES; do
        if dpkg -s "$p" >/dev/null 2>&1; then
            echo
            echo
            echo "Package $p needs to be uninstalled"
            echo
            exit 1
        fi
    done


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        ca-certificates \
        cmake \
        fxload \
        pkg-config \
        libavcodec-dev \
        libavdevice-dev \
        libboost-dev \
        libboost-regex-dev \
        libcfitsio-dev \
        libcurl4-gnutls-dev \
        libdc1394-22-dev \
        libev-dev \
        libfftw3-dev \
        libftdi1-dev \
        libftdi-dev \
        libgmock-dev \
        libgphoto2-dev \
        libgps-dev \
        libgsl-dev \
        libjpeg-dev \
        liblimesuite-dev \
        libnova-dev \
        libraw-dev \
        librtlsdr-dev \
        libtheora-dev \
        libtiff-dev \
        libusb-1.0-0-dev \
        zlib1g-dev

        #libnutclient-dev \

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then
    BLOCKING_PACKAGES="indi-full libindi-data libindi-dev libindi-plugins"
    for p in $BLOCKING_PACKAGES; do
        if dpkg -s "$p" >/dev/null 2>&1; then
            echo
            echo
            echo "Package $p needs to be uninstalled"
            echo
            exit 1
        fi
    done


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        ca-certificates \
        cmake \
        fxload \
        pkg-config \
        libavcodec-dev \
        libavdevice-dev \
        libboost-dev \
        libboost-regex-dev \
        libcfitsio-dev \
        libcurl4-gnutls-dev \
        libdc1394-22-dev \
        libev-dev \
        libfftw3-dev \
        libftdi1-dev \
        libftdi-dev \
        libgmock-dev \
        libgphoto2-dev \
        libgps-dev \
        libgsl-dev \
        libjpeg-dev \
        liblimesuite-dev \
        libnova-dev \
        libraw-dev \
        librtlsdr-dev \
        libtheora-dev \
        libtiff-dev \
        libusb-1.0-0-dev \
        zlib1g-dev

        #libnutclient-dev \

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    BLOCKING_PACKAGES="indi-full libindi-data libindi-dev libindi-plugins"
    for p in $BLOCKING_PACKAGES; do
        if dpkg -s "$p" >/dev/null 2>&1; then
            echo
            echo
            echo "Package $p needs to be uninstalled"
            echo
            exit 1
        fi
    done


    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        ca-certificates \
        cmake \
        fxload \
        pkg-config \
        libavcodec-dev \
        libavdevice-dev \
        libboost-dev \
        libboost-regex-dev \
        libcfitsio-dev \
        libcurl4-gnutls-dev \
        libdc1394-22-dev \
        libev-dev \
        libfftw3-dev \
        libftdi1-dev \
        libftdi-dev \
        libgmock-dev \
        libgphoto2-dev \
        libgps-dev \
        libgsl-dev \
        libjpeg-dev \
        liblimesuite-dev \
        libnova-dev \
        libraw-dev \
        librtlsdr-dev \
        libtheora-dev \
        libtiff-dev \
        libusb-1.0-0-dev \
        zlib1g-dev

        #libnutclient-dev \

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "22.04" ]]; then
    BLOCKING_PACKAGES="indi-full libindi-data libindi-dev libindi-plugins"
    for p in $BLOCKING_PACKAGES; do
        if dpkg -s "$p" >/dev/null 2>&1; then
            echo
            echo
            echo "Package $p needs to be uninstalled"
            echo
            exit 1
        fi
    done

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        ca-certificates \
        cmake \
        fxload \
        pkg-config \
        libavcodec-dev \
        libavdevice-dev \
        libboost-dev \
        libboost-regex-dev \
        libcfitsio-dev \
        libcurl4-gnutls-dev \
        libdc1394-dev \
        libev-dev \
        libfftw3-dev \
        libftdi1-dev \
        libftdi-dev \
        libgmock-dev \
        libgphoto2-dev \
        libgps-dev \
        libgsl-dev \
        libjpeg-dev \
        liblimesuite-dev \
        libnova-dev \
        libraw-dev \
        librtlsdr-dev \
        libtheora-dev \
        libtiff-dev \
        libusb-1.0-0-dev \
        zlib1g-dev

        #libnutclient-dev \

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then
    BLOCKING_PACKAGES="indi-full libindi-data libindi-dev libindi-plugins"
    for p in $BLOCKING_PACKAGES; do
        if dpkg -s "$p" >/dev/null 2>&1; then
            echo
            echo
            echo "Package $p needs to be uninstalled"
            echo
            exit 1
        fi
    done

    sudo apt-get update
    sudo apt-get -y install \
        build-essential \
        git \
        ca-certificates \
        cmake \
        fxload \
        pkg-config \
        libavcodec-dev \
        libavdevice-dev \
        libboost-dev \
        libboost-regex-dev \
        libcfitsio-dev \
        libcurl4-gnutls-dev \
        libdc1394-22-dev \
        libev-dev \
        libfftw3-dev \
        libftdi1-dev \
        libftdi-dev \
        libgmock-dev \
        libgphoto2-dev \
        libgps-dev \
        libgsl-dev \
        libjpeg-dev \
        liblimesuite-dev \
        libnova-dev \
        libraw-dev \
        librtlsdr-dev \
        libtheora-dev \
        libtiff-dev \
        libusb-1.0-0-dev \
        zlib1g-dev 

        #libnutclient-dev \

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


# Update library paths
sudo tee /etc/ld.so.conf.d/astro.conf <<EOF
${INSTALL_PREFIX}/lib
${INSTALL_PREFIX}/lib64
EOF

sudo ldconfig



[[ ! -d "${PROJECTS_FOLDER}" ]] && mkdir "${PROJECTS_FOLDER}"
[[ ! -d "${PROJECTS_FOLDER}/src" ]] && mkdir "${PROJECTS_FOLDER}/src"
[[ ! -d "${PROJECTS_FOLDER}/build" ]] && mkdir "${PROJECTS_FOLDER}/build"


### INDI Core ###
if [ "${BUILD_INDI_CORE:-true}" == "true" ]; then
    [[ -d "${PROJECTS_FOLDER}/src/indi_core" ]] && rm -fR "${PROJECTS_FOLDER}/src/indi_core"

    if [ "$INDI_CORE_TAG" == "HEAD" ]; then
        git clone --depth 1 "https://github.com/indilib/indi.git" "${PROJECTS_FOLDER}/src/indi_core"
    else
        git clone --depth 1 --branch "$INDI_CORE_TAG" "https://github.com/indilib/indi.git" "${PROJECTS_FOLDER}/src/indi_core"
    fi


    INDI_CORE_BUILD=$(mktemp --directory "${PROJECTS_FOLDER}/build/indi_core.XXXXXXXX")
    cd "$INDI_CORE_BUILD"

    # Setup build
    $CMAKE_BIN -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" -DCMAKE_BUILD_TYPE=Release "${PROJECTS_FOLDER}/src/indi_core"

    # Compile
    make -j "$MAKE_CONCURRENT"
    sudo make install

    cd "$OLDPWD"


    # Cleanup
    [[ -d "$INDI_CORE_BUILD" ]] && rm -fR "$INDI_CORE_BUILD"
else
    echo
    echo
    echo "Skipping indi core build"
    sleep 5
fi
### INDI Core ###



### INDI 3rdparty ###
if [ "${BUILD_INDI_3RDPARTY:-true}" == "true" ]; then
    [[ -d "${PROJECTS_FOLDER}/src/indi_core" ]] && rm -fR "${PROJECTS_FOLDER}/src/indi_3rdparty"

    if [ "$INDI_3RDPARTY_TAG" == "HEAD" ]; then
        git clone --depth 1 "https://github.com/indilib/indi-3rdparty.git" "${PROJECTS_FOLDER}/src/indi_3rdparty"
    else
        git clone --depth 1 --branch "$INDI_3RDPARTY_TAG" "https://github.com/indilib/indi-3rdparty.git" "${PROJECTS_FOLDER}/src/indi_3rdparty"
    fi


    #### libs ####
    INDI_3RDPARTY_LIB_BUILD=$(mktemp --directory "${PROJECTS_FOLDER}/build/indi_3rdparty_lib.XXXXXXXX")
    cd "$INDI_3RDPARTY_LIB_BUILD"

    # Setup library build
    $CMAKE_BIN -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" -DCMAKE_BUILD_TYPE=Release -DBUILD_LIBS=1 "${PROJECTS_FOLDER}/src/indi_3rdparty"

    # Compile
    make -j "$MAKE_CONCURRENT"
    sudo make install

    cd "$OLDPWD"
    #### libs ####



    #### drivers ####
    INDI_3RDPARTY_DRIVER_BUILD=$(mktemp --directory "${PROJECTS_FOLDER}/build/indi_3rdparty_driver.XXXXXXXX")
    cd "$INDI_3RDPARTY_DRIVER_BUILD"

    # Setup driver build
    $CMAKE_BIN -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" -DCMAKE_BUILD_TYPE=Release "${PROJECTS_FOLDER}/src/indi_3rdparty"

    # Compile
    make -j "$MAKE_CONCURRENT"
    sudo make install
    cd "$OLDPWD"
    #### drivers ####


    # Cleanup
    [[ -d "$INDI_3RDPARTY_LIB_BUILD" ]] && rm -fR "$INDI_3RDPARTY_LIB_BUILD"
    [[ -d "$INDI_3RDPARTY_DRIVER_BUILD" ]] && rm -fR "$INDI_3RDPARTY_DRIVER_BUILD"
else
    echo
    echo
    echo "Skipping indi 3rdparty build"
    sleep 5
fi
### INDI 3rdparty ###


sudo ldconfig


END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo
