#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

PATH=/bin:/usr/bin
export PATH


# can be overridden by environment variables
#BUILD_INDI_CORE="true"
#BUILD_INDI_3RDPARTY="true"
#BUILD_INDI_CAMERA_VENDOR="zwo"
#MAKE_CONCURRENT=x


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
    #INDI_CORE_TAG="HEAD"
    INDI_CORE_TAG="v2.1.1"
    INDI_3RDPARTY_TAG=$INDI_CORE_TAG
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

CMAKE_BIN=cmake
INSTALL_PREFIX="/usr/local"


MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk "{print \$2}")


if [ -z "${MAKE_CONCURRENT:-}" ]; then
    if [ "$MEM_TOTAL" -lt "1536000" ]; then
        # <= 1GB memory should use 1 process
        MAKE_CONCURRENT=1
    elif [ "$MEM_TOTAL" -lt "2560000" ]; then
        # 2GB memory should use 2 processes
        MAKE_CONCURRENT=2
    else
        MAKE_CONCURRENT=$(nproc)
    fi
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


if [[ "$CPU_ARCH" == "aarch64" && "$CPU_BITS" == "32" ]]; then
    echo
    echo
    echo "INDI 3rd party drivers will not build properly on Raspbian 32-bit running a 64-bit kernel"
    echo "You must add the following parameter to /boot/firmware/config.txt and reboot:"
    echo
    echo "  arm_64bit=0"
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
echo "Indi core:     $INDI_CORE_TAG"
echo "Indi 3rdparty: $INDI_3RDPARTY_TAG"
echo
echo "Existing INDI: ${DETECTED_INDIVERSION:-none}"
echo
echo "BUILD_INDI_CORE: ${BUILD_INDI_CORE:-true}"
echo "BUILD_INDI_3RDPARTY: ${BUILD_INDI_3RDPARTY:-true}"
echo "BUILD_INDI_CAMERA_VENDOR: ${BUILD_INDI_CAMERA_VENDOR:-ask}"
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
            whiptail \
            fxload \
            pkgconf \
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
            libnutclient-dev \
            libzmq3-dev \
            libahp-gt-dev \
            zlib1g-dev


    elif [[ "$DISTRO_VERSION_ID" == "11" ]]; then
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
            whiptail \
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
            libnutclient-dev \
            libzmq3-dev \
            zlib1g-dev


    elif [[ "$DISTRO_VERSION_ID" == "10" ]]; then
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
            whiptail \
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

    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi
elif [[ "$DISTRO_ID" == "ubuntu" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "24.04" ]]; then
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
            whiptail \
            fxload \
            pkgconf \
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
            libnutclient-dev \
            libzmq3-dev \
            libahp-gt-dev \
            zlib1g-dev

    elif [[ "$DISTRO_VERSION_ID" == "22.04" ]]; then
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
            whiptail \
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
            libnutclient-dev \
            libzmq3-dev \
            zlib1g-dev

    elif [[ "$DISTRO_VERSION_ID" == "20.04" ]]; then
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
            whiptail \
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
            libzmq3-dev \
            zlib1g-dev
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
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


if [ "${BUILD_INDI_3RDPARTY:-true}" == "true" ]; then
    while [ "${BUILD_INDI_CAMERA_VENDOR:-ask}" == "ask" ]; do
        BUILD_INDI_CAMERA_VENDOR=$(whiptail \
            --title "Camera Vendor" \
            --nocancel \
            --notags \
            --radiolist "Select which camera vendor to build\n\nPress space to select" 0 0 0 \
                "supported" "Supported Cameras" "OFF" \
                "asi" "ZWO ASI Camera" "OFF" \
                "playerone" "PlayerOne Astronomy" "OFF" \
                "touptek" "ToupTek / Altair / Omegon / Meade / etc" "OFF" \
                "svbony" "SVBony" "OFF" \
                "qhy" "QHY" "OFF" \
                "sx" "Starlight Xpress" "OFF" \
                "libcamera" "indi-libcamera [BETA] (this is not the standard libcamera support)" "OFF" \
                "gphoto" "DSLR - Canon / Nikon / Sony / Pentax / Fuji / etc" "OFF" \
                "webcam" "Web Camera - indi_webcam_ccd" "OFF" \
                "all" "All drivers" "OFF" \
            3>&1 1>&2 2>&3)
    done


    if [[ "$BUILD_INDI_CAMERA_VENDOR" == "all" ]]; then
        INDI_3RDPARTY_LIBRARIES="all"
        INDI_3RDPARTY_DRIVERS="all"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "asi" || "$BUILD_INDI_CAMERA_VENDOR" == "zwo" ]]; then
        INDI_3RDPARTY_LIBRARIES="libasi"
        INDI_3RDPARTY_DRIVERS="indi-asi indi-gpsd"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "playerone" ]]; then
        INDI_3RDPARTY_LIBRARIES="libplayerone"
        INDI_3RDPARTY_DRIVERS="indi-playerone indi-gpsd"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "svbony" ]]; then
        INDI_3RDPARTY_LIBRARIES="libsvbony"
        INDI_3RDPARTY_DRIVERS="indi-svbony indi-gpsd"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "qhy" ]]; then
        INDI_3RDPARTY_LIBRARIES="libqhy"
        INDI_3RDPARTY_DRIVERS="indi-qhy indi-gpsd"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "sx" ]]; then
        INDI_3RDPARTY_LIBRARIES=""
        INDI_3RDPARTY_DRIVERS="indi-sx indi-gpsd"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "libcamera" ]]; then
        INDI_3RDPARTY_LIBRARIES=""
        INDI_3RDPARTY_DRIVERS="indi-libcamera indi-gpsd"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "gphoto" ]]; then
        INDI_3RDPARTY_LIBRARIES=""
        INDI_3RDPARTY_DRIVERS="indi-gphoto indi-gpsd"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "webcam" ]]; then
        INDI_3RDPARTY_LIBRARIES=""
        INDI_3RDPARTY_DRIVERS="indi-webcam indi-gpsd"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "touptek" ]]; then
        INDI_3RDPARTY_LIBRARIES="libtoupcam libaltaircam libbressercam libmallincam libmeadecam libnncam libogmacam libomegonprocam libstarshootg libtscam indi-gpsd"
        INDI_3RDPARTY_DRIVERS="indi-toupbase"
    elif [[ "$BUILD_INDI_CAMERA_VENDOR" == "supported" ]]; then
        INDI_3RDPARTY_LIBRARIES="libasi libplayerone libsvbony libqhy libtoupcam libaltaircam libbressercam libmallincam libmeadecam libnncam libogmacam libomegonprocam libstarshootg libtscam"
        INDI_3RDPARTY_DRIVERS="indi-asi indi-playerone indi-svbony indi-qhy indi-sx indi-toupbase indi-gphoto indi-webcam indi-gpsd"
    else
        echo
        echo "Invalid selection"
        exit 1
    fi
fi


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


sudo ldconfig


### INDI 3rdparty ###
if [ "${BUILD_INDI_3RDPARTY:-true}" == "true" ]; then
    [[ -d "${PROJECTS_FOLDER}/src/indi_core" ]] && rm -fR "${PROJECTS_FOLDER}/src/indi_3rdparty"

    if [ "$INDI_3RDPARTY_TAG" == "HEAD" ]; then
        git clone --depth 1 "https://github.com/indilib/indi-3rdparty.git" "${PROJECTS_FOLDER}/src/indi_3rdparty"
    else
        git clone --depth 1 --branch "$INDI_3RDPARTY_TAG" "https://github.com/indilib/indi-3rdparty.git" "${PROJECTS_FOLDER}/src/indi_3rdparty"
    fi


    if [ "${BUILD_INDI_3RDPARTY_LIB:-true}" == "true" ]; then
        #### libs ####
        if [ "$INDI_3RDPARTY_LIBRARIES" == "all" ]; then
            INDI_3RDPARTY_LIB_BUILD=$(mktemp --directory "${PROJECTS_FOLDER}/build/indi_3rdparty_lib.XXXXXXXX")
            cd "$INDI_3RDPARTY_LIB_BUILD"


            # Setup library build
            $CMAKE_BIN -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" -DCMAKE_BUILD_TYPE=Release -DBUILD_LIBS=1 "${PROJECTS_FOLDER}/src/indi_3rdparty"

            # Compile
            make -j "$MAKE_CONCURRENT"
            sudo make install

            cd "$OLDPWD"


            # Cleanup
            [[ -d "$INDI_3RDPARTY_LIB_BUILD" ]] && rm -fR "$INDI_3RDPARTY_LIB_BUILD"
        else
            for INDI_LIB in $INDI_3RDPARTY_LIBRARIES; do
                echo
                echo "Building library: $INDI_LIB"
                echo
                sleep 3

                INDI_3RDPARTY_LIB_BUILD=$(mktemp --directory "${PROJECTS_FOLDER}/build/indi_3rdparty_lib.XXXXXXXX")
                cd "$INDI_3RDPARTY_LIB_BUILD"


                # Setup library build
                $CMAKE_BIN -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" -DCMAKE_BUILD_TYPE=Release "${PROJECTS_FOLDER}/src/indi_3rdparty/$INDI_LIB"

                # Compile
                make -j "$MAKE_CONCURRENT"
                sudo make install

                cd "$OLDPWD"


                # Cleanup
                [[ -d "$INDI_3RDPARTY_LIB_BUILD" ]] && rm -fR "$INDI_3RDPARTY_LIB_BUILD"
            done
        fi
        #### libs ####
    else
        echo
        echo
        echo "Skipping indi 3rdparty library build"
        sleep 5
    fi


    if [ "${BUILD_INDI_3RDPARTY_DRIVER:-true}" == "true" ]; then
        #### drivers ####
        if [ "$INDI_3RDPARTY_DRIVERS" == "all" ]; then
            INDI_3RDPARTY_DRIVER_BUILD=$(mktemp --directory "${PROJECTS_FOLDER}/build/indi_3rdparty_driver.XXXXXXXX")
            cd "$INDI_3RDPARTY_DRIVER_BUILD"

            # Setup driver build
            $CMAKE_BIN -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" -DCMAKE_BUILD_TYPE=Release "${PROJECTS_FOLDER}/src/indi_3rdparty"

            # Compile
            make -j "$MAKE_CONCURRENT"
            sudo make install
            cd "$OLDPWD"


            # Cleanup
            [[ -d "$INDI_3RDPARTY_DRIVER_BUILD" ]] && rm -fR "$INDI_3RDPARTY_DRIVER_BUILD"
        else
            for INDI_DRIVER in $INDI_3RDPARTY_DRIVERS; do
                echo
                echo "Building driver: $INDI_DRIVER"
                echo
                sleep 3

                INDI_3RDPARTY_DRIVER_BUILD=$(mktemp --directory "${PROJECTS_FOLDER}/build/indi_3rdparty_driver.XXXXXXXX")
                cd "$INDI_3RDPARTY_DRIVER_BUILD"

                # Setup driver build
                $CMAKE_BIN -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" -DCMAKE_BUILD_TYPE=Release "${PROJECTS_FOLDER}/src/indi_3rdparty/$INDI_DRIVER"

                # Compile
                make -j "$MAKE_CONCURRENT"
                sudo make install
                cd "$OLDPWD"


                # Cleanup
                [[ -d "$INDI_3RDPARTY_DRIVER_BUILD" ]] && rm -fR "$INDI_3RDPARTY_DRIVER_BUILD"
            done
        fi
        #### drivers ####
    else
        echo
        echo
        echo "Skipping indi 3rdparty driver build"
        sleep 5
    fi
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
