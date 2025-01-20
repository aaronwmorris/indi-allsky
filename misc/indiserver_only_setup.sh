#!/bin/bash

#set -x  # command tracing
set -o errexit  # replace by trapping ERR
set -o nounset  # problems with python virtualenvs
shopt -s nullglob

PATH=/usr/bin:/bin
export PATH


#### config ####
INDI_DRIVER_PATH="/usr/bin"
INDISERVER_SERVICE_NAME="indiserver"
INSTALL_INDI="${INDIALLSKY_INSTALL_INDI:-true}"
INSTALL_INDISERVER="${INDIALLSKY_INSTALL_INDISERVER:-}"
CCD_DRIVER="${INDIALLSKY_CCD_DRIVER:-}"
GPS_DRIVER="${INDIALLSKY_GPS_DRIVER:-}"
INDI_PORT="${INDIALLSKY_INDI_PORT:-7624}"



function catch_error() {
    echo
    echo
    echo "###############"
    echo "###  ERROR  ###"
    echo "###############"
    echo
    echo "The setup script exited abnormally, please try to run again..."
    echo
    echo
    exit 1
}
trap catch_error ERR

function catch_sigint() {
    echo
    echo
    echo "###############"
    echo "###  ERROR  ###"
    echo "###############"
    echo
    echo "The setup script was interrupted, please run the script again to finish..."
    echo
    exit 1
}
trap catch_sigint SIGINT


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



echo "##########################################################"
echo "### Welcome to the indi-allsky indiserver setup script ###"
echo "##########################################################"


if ! [[ "$INDI_PORT" =~ ^[^0][0-9]{1,5}$ ]]; then
    echo "Invalid INDI port: $INDI_PORT"
    echo
    exit 1
fi


if [ -f "/usr/local/bin/indiserver" ]; then
    # Do not install INDI
    INSTALL_INDI="false"
    INDI_DRIVER_PATH="/usr/local/bin"

    echo
    echo
    echo "Detected a custom installation of INDI in /usr/local/bin"
    echo
    echo
    sleep 3
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
echo "INDI_DRIVER_PATH: $INDI_DRIVER_PATH"
echo "INDISERVER_SERVICE_NAME: $INDISERVER_SERVICE_NAME"
echo "INSTALL_INDI: $INSTALL_INDI"
echo
echo


if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


START_TIME=$(date +%s)


echo
echo
echo "indi-allsky supports the following camera interfaces."
echo
echo "Wiki:  https://github.com/aaronwmorris/indi-allsky/wiki/Camera-Interfaces"
echo
echo "             indi: For astro/planetary cameras normally connected via USB (ZWO, QHY, PlayerOne, SVBony, Altair, Touptek, etc)"
echo "        libcamera: Supports cameras connected via CSI interface on Raspberry Pi SBCs (Raspi HQ Camera, Camera Module 3, etc)"
echo "    pycurl_camera: Download images from a remote web camera"
echo " indi_accumulator: Create synthetic exposures using multiple sub-exposures"
echo "     indi_passive: Connect a second instance of indi-allsky to an existing indi-allsky indiserver"
echo

# whiptail might not be installed yet
while [ -z "${CAMERA_INTERFACE:-}" ]; do
    PS3="Select a camera interface: "
    select camera_interface in indi libcamera pycurl_camera indi_accumulator indi_passive ; do
        if [ -n "$camera_interface" ]; then
            CAMERA_INTERFACE=$camera_interface
            break
        fi
    done


    # more specific libcamera selection
    if [ "$CAMERA_INTERFACE" == "libcamera" ]; then
        echo
        PS3="Select a libcamera interface: "
        select libcamera_interface in libcamera_imx477 libcamera_imx378 libcamera_imx708 libcamera_imx519 libcamera_imx500_ai libcamera_imx283 libcamera_imx462 libcamera_imx327 libcamera_imx678 libcamera_ov5647 libcamera_imx219 libcamera_imx296_gs libcamera_imx290 libcamera_imx298 libcamera_64mp_hawkeye libcamera_64mp_owlsight; do
            if [ -n "$libcamera_interface" ]; then
                # overwrite variable
                CAMERA_INTERFACE=$libcamera_interface
                break
            fi
        done
    fi
done



echo "**** Installing packages... ****"
if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "raspbian" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "12" ]]; then

        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi

    elif [[ "$DISTRO_VERSION_ID" == "11" ]]; then

        INSTALL_INDI="false"

        if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
            echo
            echo
            echo "There are not prebuilt indi packages for this distribution"
            echo "Please run ./misc/build_indi.sh before running setup.sh"
            echo
            echo
            exit 1
        fi

    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "ubuntu" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "24.04" ]]; then

        if [[ "$CPU_ARCH" == "x86_64" && "$CPU_BITS" == "64" ]]; then
            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                sudo add-apt-repository -y ppa:mutlaqja/ppa
            fi
        elif [[ "$CPU_ARCH" == "aarch64" && "$CPU_BITS" == "64" ]]; then
            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                sudo add-apt-repository -y ppa:mutlaqja/ppa
            fi
        else
            INSTALL_INDI="false"

            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                echo
                echo
                echo "There are not prebuilt indi packages for this distribution"
                echo "Please run ./misc/build_indi.sh before running setup.sh"
                echo
                echo
                exit 1
            fi
        fi

        if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
            if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
                INSTALL_INDI="false"
            fi
        fi

        if [[ "$INSTALL_INDI" == "true" ]]; then
            sudo apt-get -y install \
                indi-full \
                libindi-dev \
                indi-webcam \
                indi-asi \
                libasi \
                indi-qhy \
                libqhy \
                indi-playerone \
                libplayerone \
                indi-svbony \
                libsvbony \
                libaltaircam \
                libmallincam \
                libmicam \
                libnncam \
                indi-toupbase \
                libtoupcam \
                indi-gphoto \
                indi-sx \
                indi-gpsd \
                indi-gpsnmea
        fi


    elif [[ "$DISTRO_VERSION_ID" == "22.04" ]]; then

        if [[ "$CPU_ARCH" == "x86_64" && "$CPU_BITS" == "64" ]]; then
            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                sudo add-apt-repository -y ppa:mutlaqja/ppa
            fi
        elif [[ "$CPU_ARCH" == "aarch64" && "$CPU_BITS" == "64" ]]; then
            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                sudo add-apt-repository -y ppa:mutlaqja/ppa
            fi
        else
            INSTALL_INDI="false"

            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                echo
                echo
                echo "There are not prebuilt indi packages for this distribution"
                echo "Please run ./misc/build_indi.sh before running setup.sh"
                echo
                echo
                exit 1
            fi
        fi

        if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
            if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
                INSTALL_INDI="false"
            fi
        fi

        if [[ "$INSTALL_INDI" == "true" ]]; then
            sudo apt-get -y install \
                indi-full \
                libindi-dev \
                indi-webcam \
                indi-asi \
                libasi \
                indi-qhy \
                libqhy \
                indi-playerone \
                libplayerone \
                indi-svbony \
                libsvbony \
                libaltaircam \
                libmallincam \
                libmicam \
                libnncam \
                indi-toupbase \
                libtoupcam \
                indi-gphoto \
                indi-sx \
                indi-gpsd \
                indi-gpsnmea
        fi

    elif [[ "$DISTRO_VERSION_ID" == "20.04" ]]; then

        if [[ "$CPU_ARCH" == "x86_64" && "$CPU_BITS" == "64" ]]; then
            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                sudo add-apt-repository -y ppa:mutlaqja/ppa
            fi
        elif [[ "$CPU_ARCH" == "aarch64" && "$CPU_BITS" == "64" ]]; then
            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                sudo add-apt-repository -y ppa:mutlaqja/ppa
            fi
        else
            INSTALL_INDI="false"

            if [[ ! -f "${INDI_DRIVER_PATH}/indiserver" && ! -f "/usr/local/bin/indiserver" ]]; then
                echo
                echo
                echo "There are not prebuilt indi packages for this distribution"
                echo "Please run ./misc/build_indi.sh before running setup.sh"
                echo
                echo
                exit 1
            fi
        fi

        if [[ "$INSTALL_INDI" == "true" && -f "/usr/bin/indiserver" ]]; then
            if ! whiptail --title "indi software update" --yesno "INDI is already installed, would you like to upgrade the software?" 0 0 --defaultno; then
                INSTALL_INDI="false"
            fi
        fi

        if [[ "$INSTALL_INDI" == "true" ]]; then
            sudo apt-get -y install \
                indi-full \
                libindi-dev \
                indi-webcam \
                indi-asi \
                libasi \
                indi-qhy \
                libqhy \
                indi-playerone \
                libplayerone \
                indi-svbony \
                libsvbony \
                libaltaircam \
                libmallincam \
                libmicam \
                libnncam \
                indi-toupbase \
                libtoupcam \
                indi-gphoto \
                indi-sx \
                indi-gpsd \
                indi-gpsnmea
        fi
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


if [ -z "$DBUS_SESSION_BUS_ADDRESS" ]; then
    echo
    echo
    echo "The DBUS user session is not defined"
    echo
    echo "WARNING: If you use screen, tmux, or byobu for virtual sessions, this check may always fail"
    echo
    exit 1
fi


if systemctl -q is-enabled "${INDISERVER_SERVICE_NAME}" 2>/dev/null; then
    # system
    INSTALL_INDISERVER="false"
elif systemctl --user -q is-enabled "${INDISERVER_SERVICE_NAME}.timer" 2>/dev/null; then
    while [ -z "${INSTALL_INDISERVER:-}" ]; do
        # user
        if whiptail --title "indiserver update" --yesno "An indiserver service is already defined, would you like to replace it?" 0 0 --defaultno; then
            INSTALL_INDISERVER="true"
        else
            INSTALL_INDISERVER="false"
        fi
    done
else
    INSTALL_INDISERVER="true"
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.." || catch_error
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD" || catch_error


# get list of ccd drivers
INDI_CCD_DRIVERS=()
cd "$INDI_DRIVER_PATH" || catch_error
for I in indi_*_ccd indi_rpicam* indi_pylibcamera*; do
    INDI_CCD_DRIVERS[${#INDI_CCD_DRIVERS[@]}]="$I $I OFF"
done
cd "$OLDPWD" || catch_error

#echo ${INDI_CCD_DRIVERS[@]}


if [[ "$INSTALL_INDISERVER" == "true" ]]; then
    if [[ "$CAMERA_INTERFACE" == "indi" || "$CAMERA_INTERFACE" == "indi_accumulator" ]]; then
        while [ -z "${CCD_DRIVER:-}" ]; do
            # shellcheck disable=SC2068
            CCD_DRIVER=$(whiptail --title "Camera Driver" --nocancel --notags --radiolist "Press space to select" 0 0 0 ${INDI_CCD_DRIVERS[@]} 3>&1 1>&2 2>&3)
        done
    else
        # simulator will not affect anything
        CCD_DRIVER=indi_simulator_ccd
    fi
fi

#echo $CCD_DRIVER


# get list of gps drivers
INDI_GPS_DRIVERS=("None None ON")
cd "$INDI_DRIVER_PATH" || catch_error
for I in indi_gps* indi_simulator_gps; do
    INDI_GPS_DRIVERS[${#INDI_GPS_DRIVERS[@]}]="$I $I OFF"
done
cd "$OLDPWD" || catch_error

#echo ${INDI_GPS_DRIVERS[@]}


if [[ "$INSTALL_INDISERVER" == "true" ]]; then
    while [ -z "${GPS_DRIVER:-}" ]; do
        # shellcheck disable=SC2068
        GPS_DRIVER=$(whiptail --title "GPS Driver" --nocancel --notags --radiolist "Press space to select" 0 0 0 ${INDI_GPS_DRIVERS[@]} 3>&1 1>&2 2>&3)
    done
fi

#echo $GPS_DRIVER

if [ "$GPS_DRIVER" == "None" ]; then
    # Value needs to be empty for None
    GPS_DRIVER=""
fi


# create users systemd folder
[[ ! -d "${HOME}/.config/systemd/user" ]] && mkdir -p "${HOME}/.config/systemd/user"


if [ "$INSTALL_INDISERVER" == "true" ]; then
    echo
    echo
    echo "**** Setting up indiserver service ****"


    # timer
    cp -f "${ALLSKY_DIRECTORY}/service/${INDISERVER_SERVICE_NAME}.timer" "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.timer"
    chmod 644 "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.timer"


    TMP1=$(mktemp)
    sed \
     -e "s|%INDI_DRIVER_PATH%|$INDI_DRIVER_PATH|g" \
     -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
     -e "s|%INDISERVER_USER%|$USER|g" \
     -e "s|%INDI_PORT%|$INDI_PORT|g" \
     -e "s|%INDI_CCD_DRIVER%|$CCD_DRIVER|g" \
     -e "s|%INDI_GPS_DRIVER%|$GPS_DRIVER|g" \
     "${ALLSKY_DIRECTORY}/service/indiserver.service" > "$TMP1"


    cp -f "$TMP1" "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.service"
    chmod 644 "${HOME}/.config/systemd/user/${INDISERVER_SERVICE_NAME}.service"
    [[ -f "$TMP1" ]] && rm -f "$TMP1"

else
    echo
    echo
    echo
    echo "! Bypassing indiserver setup"
fi


systemctl --user daemon-reload


if [ "$INSTALL_INDISERVER" == "true" ]; then
    # service started by timer
    systemctl --user disable ${INDISERVER_SERVICE_NAME}.service
    systemctl --user enable ${INDISERVER_SERVICE_NAME}.timer


    while [ -z "${RESTART_INDISERVER:-}" ]; do
        if whiptail --title "Restart indiserver" --yesno "Do you want to restart the indiserver now?\n\nNot recommended if the indi-allsky service is active." 0 0 --defaultno; then
            RESTART_INDISERVER="true"
        else
            RESTART_INDISERVER="false"
        fi
    done


    if [ "$RESTART_INDISERVER" == "true" ]; then
        echo "Restarting indiserver..."
        sleep 3
        systemctl --user restart ${INDISERVER_SERVICE_NAME}.service
    else
        echo
        echo
        echo
        echo
        echo "You now need to restart the indiserver service to activate the driver change"
        echo
        echo "    systemctl --user restart $INDISERVER_SERVICE_NAME"
        echo
    fi
fi

END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo

echo
echo "Enjoy!"
