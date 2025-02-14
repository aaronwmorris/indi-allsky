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


LIBCAMERA_GIT_URL="https://github.com/raspberrypi/libcamera"
#LIBCAMERA_GIT_URL="https://git.libcamera.org/libcamera/libcamera.git"

RPICAM_APPS_GIT_URL="https://github.com/raspberrypi/rpicam-apps.git"


if [ -n "${1:-}" ]; then
    LIBCAMERA_TAG="$1"
else
    #LIBCAMERA_TAG="HEAD"
    LIBCAMERA_TAG="v0.3.0+rpt20240617"
    #LIBCAMERA_TAG="v0.3.1"
fi

if [ -n "${2:-}" ]; then
    RPICAM_APPS_TAG="$2"
else
    #RPICAM_APPS_TAG="HEAD"
    RPICAM_APPS_TAG="v1.5.0"
fi


if [ ! -f "/etc/os-release" ]; then
    echo
    echo "Unable to determine OS from /etc/os-release"
    echo
    exit 1
fi

source /etc/os-release


DISTRO_ID="${ID:-unknown}"
DISTRO_VERSION_ID="${VERSION_ID:-unknown}"
CPU_ARCH=$(uname -m)
CPU_BITS=$(getconf LONG_BIT)
CPU_TOTAL=$(grep -c "^proc" /proc/cpuinfo)
MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk "{print \$2}")


PROJECTS_FOLDER="$HOME/Projects"


MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk "{print \$2}")
if [ "$MEM_TOTAL" -lt "1536000" ]; then
    # <= 1GB memory should use 1 process
    MAKE_CONCURRENT=1
elif [ "$MEM_TOTAL" -lt "2560000" ]; then
    # 2GB memory should use 2 processes
    MAKE_CONCURRENT=2
else
    MAKE_CONCURRENT=$(nproc)
fi


echo "###########################################################"
echo "### Welcome to the indi-allsky libcamera compile script ###"
echo "###########################################################"


# sanity check
if [[ "$(id -u)" == "0" ]]; then
    echo
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


echo
echo
echo "Distribution: $DISTRO_ID"
echo "Release: $DISTRO_VERSION_ID"
echo "Arch: $CPU_ARCH"
echo "Bits: $CPU_BITS"
echo
echo "CPUs: $CPU_TOTAL"
echo "Memory: $MEM_TOTAL kB"
echo
echo "libcamera:   $LIBCAMERA_TAG"
echo "rpicam-apps: $RPICAM_APPS_TAG"
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
if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "raspbian" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "12" ]]; then
        BLOCKING_PACKAGES="libcamera libcamera-apps libcamera-apps-lite rpicam-apps rpicam-apps-lite"
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
            python3-dev \
            libtiff5-dev \
            libjpeg62-turbo-dev \
            libpng-dev \
            libepoxy-dev \
            python3-pip python3-jinja2 \
            libboost-dev \
            libgnutls28-dev openssl libtiff5-dev pybind11-dev \
            qtbase5-dev libqt5core5a libqt5gui5 libqt5widgets5 \
            meson cmake \
            python3-yaml python3-ply \
            libglib2.0-dev libgstreamer-plugins-base1.0-dev \
            libboost-program-options-dev libdrm-dev libexif-dev \
            ninja-build


    elif [[ "$DISTRO_VERSION_ID" == "11" ]]; then
        BLOCKING_PACKAGES="libcamera libcamera-apps libcamera-apps-lite"
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
            python3-dev \
            libepoxy-dev \
            python3-pip python3-jinja2 \
            libboost-dev \
            libgnutls28-dev openssl libtiff5-dev pybind11-dev \
            qtbase5-dev libqt5core5a libqt5gui5 libqt5widgets5 \
            meson cmake \
            python3-yaml python3-ply \
            libglib2.0-dev libgstreamer-plugins-base1.0-dev \
            libboost-program-options-dev libdrm-dev libexif-dev \
            ninja-build

    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "ubuntu" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "24.04" ]]; then
        BLOCKING_PACKAGES="libcamera libcamera-apps libcamera-apps-lite rpicam-apps rpicam-apps-lite"
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
            python3-dev \
            libtiff5-dev \
            libjpeg8-dev \
            libpng-dev \
            libepoxy-dev \
            python3-pip python3-jinja2 \
            libboost-dev \
            libgnutls28-dev openssl libtiff5-dev pybind11-dev \
            qtbase5-dev libqt5core5a libqt5gui5 libqt5widgets5 \
            meson cmake \
            python3-yaml python3-ply \
            libglib2.0-dev libgstreamer-plugins-base1.0-dev \
            libboost-program-options-dev libdrm-dev libexif-dev \
            ninja-build


    elif [[ "$DISTRO_VERSION_ID" == "22.04" ]]; then
        BLOCKING_PACKAGES="libcamera libcamera-apps"
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
            python3-dev \
            libtiff5-dev \
            libjpeg8-dev \
            libpng-dev \
            libepoxy-dev \
            python3-pip python3-jinja2 \
            libboost-dev \
            libgnutls28-dev openssl libtiff5-dev pybind11-dev \
            qtbase5-dev libqt5core5a libqt5gui5 libqt5widgets5 \
            meson cmake \
            python3-yaml python3-ply \
            libglib2.0-dev libgstreamer-plugins-base1.0-dev \
            libboost-program-options-dev libdrm-dev libexif-dev \
            ninja-build


    elif [[ "$DISTRO_VERSION_ID" == "20.04" ]]; then
        BLOCKING_PACKAGES="libcamera libcamera-apps"
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
            python3-dev \
            libtiff5-dev \
            libjpeg8-dev \
            libpng-dev \
            libepoxy-dev \
            python3-pip python3-jinja2 \
            libboost-dev \
            libgnutls28-dev openssl libtiff5-dev pybind11-dev \
            qtbase5-dev libqt5core5a libqt5gui5 libqt5widgets5 \
            meson cmake \
            python3-yaml python3-ply \
            libglib2.0-dev libgstreamer-plugins-base1.0-dev \
            libboost-program-options-dev libdrm-dev libexif-dev \
            ninja-build
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


sudo ldconfig



[[ ! -d "${PROJECTS_FOLDER}" ]] && mkdir "${PROJECTS_FOLDER}"
[[ ! -d "${PROJECTS_FOLDER}/src" ]] && mkdir "${PROJECTS_FOLDER}/src"


### libcamera ###
if [ "${BUILD_LIBCAMERA:-true}" == "true" ]; then
    [[ -d "${PROJECTS_FOLDER}/src/libcamera" ]] && rm -fR "${PROJECTS_FOLDER}/src/libcamera"

    # log this for debugging
    echo "git libcamera tag: $LIBCAMERA_TAG"
    echo

    if [ "$LIBCAMERA_TAG" == "HEAD" ]; then
        git clone --depth 1 "$LIBCAMERA_GIT_URL=" "${PROJECTS_FOLDER}/src/libcamera"
    else
        git clone --depth 1 --branch "$LIBCAMERA_TAG" "$LIBCAMERA_GIT_URL=" "${PROJECTS_FOLDER}/src/libcamera"
    fi


    cd "${PROJECTS_FOLDER}/src/libcamera"

    # Setup build
    meson setup build --buildtype=release -Dpipelines=rpi/vc4,rpi/pisp -Dipas=rpi/vc4,rpi/pisp -Dv4l2=true -Dgstreamer=enabled -Dtest=false -Dlc-compliance=disabled -Dcam=disabled -Dqcam=disabled -Ddocumentation=disabled -Dpycamera=enabled

    ### without PISP (Pi5)
    #meson setup build --buildtype=release -Dpipelines=rpi/vc4 -Dipas=rpi/vc4 -Dv4l2=true -Dgstreamer=enabled -Dtest=false -Dlc-compliance=disabled -Dcam=disabled -Dqcam=disabled -Ddocumentation=disabled -Dpycamera=enabled

    # Compile
    ninja -C build -j "$MAKE_CONCURRENT"
    sudo ninja -C build install

    cd "$OLDPWD"


else
    echo
    echo
    echo "Skipping libcamera build"
    sleep 5
fi
### libcamera ###


sudo ldconfig


### rpicam-apps ###
if [ "${BUILD_RPICAM_APPS:-true}" == "true" ]; then
    [[ -d "${PROJECTS_FOLDER}/src/rpicam-apps" ]] && rm -fR "${PROJECTS_FOLDER}/src/rpicam-apps"

    # log this for debugging
    echo "git rpicam apps tag: $RPICAM_APPS_TAG"
    echo

    if [ "$RPICAM_APPS_TAG" == "HEAD" ]; then
        git clone --depth 1 "$RPICAM_APPS_GIT_URL" "${PROJECTS_FOLDER}/src/rpicam-apps"
    else
        git clone --depth 1 --branch "$RPICAM_APPS_TAG" "$RPICAM_APPS_GIT_URL" "${PROJECTS_FOLDER}/src/rpicam-apps"
    fi


    cd "${PROJECTS_FOLDER}/src/rpicam-apps"


    # Setup build
    #meson setup build -Denable_libav=disabled -Denable_drm=enabled -Denable_egl=disabled -Denable_qt=disabled -Denable_opencv=disabled -Denable_tflite=disabled
    meson setup build -Denable_libav=enabled -Denable_drm=enabled -Denable_egl=enabled -Denable_qt=enabled -Denable_opencv=disabled -Denable_tflite=disabled

    # Compile
    meson compile -C build -j "$MAKE_CONCURRENT"
    sudo meson install -C build

    cd "$OLDPWD"
else
    echo
    echo
    echo "Skipping rpicam-apps build"
    sleep 5
fi
### rpicam-apps ###


sudo ldconfig


END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo
