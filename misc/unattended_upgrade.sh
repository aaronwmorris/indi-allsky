#!/bin/bash
# shellcheck disable=SC2317  #DEVELOPMENT

#set -x  # command tracing
#set -o errexit  # replace by trapping ERR
#set -o nounset  # problems with python virtualenvs
shopt -s nullglob

PATH=/usr/bin:/bin
export PATH


#### config ####
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"

ALLSKY_ETC="/etc/indi-allsky"
DB_FOLDER="/var/lib/indi-allsky"
DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"

OPTIONAL_PYTHON_MODULES="${INDIALLSKY_OPTIONAL_PYTHON_MODULES:-true}"
GPIO_PYTHON_MODULES="${INDIALLSKY_GPIO_PYTHON_MODULES:-true}"

PYINDI_2_0_4="git+https://github.com/indilib/pyindi-client.git@d8ad88f#egg=pyindi-client"
PYINDI_2_0_0="git+https://github.com/indilib/pyindi-client.git@674706f#egg=pyindi-client"
PYINDI_1_9_9="git+https://github.com/indilib/pyindi-client.git@ce808b7#egg=pyindi-client"
PYINDI_1_9_8="git+https://github.com/indilib/pyindi-client.git@ffd939b#egg=pyindi-client"
#### end config ####


function catch_error() {
    echo
    echo
    echo "###############"
    echo "###  ERROR  ###"
    echo "###############"
    echo
    echo "The upgrade script exited abnormally, please try to run again..."
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
    echo "The upgrade script was interrupted, please run the script again to finish..."
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


### this will be removed after development
echo
echo "This script is a work in progress... exiting"
exit 1



DISTRO_ID="${ID:-unknown}"
DISTRO_VERSION_ID="${VERSION_ID:-unknown}"
CPU_ARCH=$(uname -m)
CPU_BITS=$(getconf LONG_BIT)
CPU_TOTAL=$(grep -c "^proc" /proc/cpuinfo)
MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk "{print \$2}")


echo "############################################################"
echo "### Welcome to the indi-allsky unattended upgrade script ###"
echo "############################################################"


if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo
    echo "Please do not run $(basename "$0") with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
    echo
    echo
    exit 1
fi


if systemctl --user --quiet is-active "${ALLSKY_SERVICE_NAME}.service" >/dev/null 2>&1; then
    echo
    echo
    echo "WARNING: indi-allsky is running.  The service will be stopped during the upgrade"
    echo
    sleep 3
fi


if [[ "$(id -u)" == "0" ]]; then
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


if systemctl --quiet is-enabled "${ALLSKY_SERVICE_NAME}.timer" 2>/dev/null; then
    ### make sure the timer is not started
    systemctl --user stop "${ALLSKY_SERVICE_NAME}.timer"
fi


echo "Upgrade proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "raspbian" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "12" ]]; then
        DISTRO="debian_12"
    elif [[ "$DISTRO_VERSION_ID" == "11" ]]; then
        DISTRO="debian_11"
    elif [[ "$DISTRO_VERSION_ID" == "10" ]]; then
        DISTRO="debian_10"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "ubuntu" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "24.04" ]]; then
        DISTRO="ubuntu_24.04"
    elif [[ "$DISTRO_VERSION_ID" == "22.04" ]]; then
        DISTRO="ubuntu_22.04"
    elif [[ "$DISTRO_VERSION_ID" == "20.04" ]]; then
        DISTRO="ubuntu_20.04"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "linuxmint" ]]; then
    if [[ "$DISTRO_VERSION_ID" =~ ^22 ]]; then
        DISTRO="ubuntu_24.04"
    elif [[ "$DISTRO_VERSION_ID" =~ ^21 ]]; then
        DISTRO="ubuntu_22.04"
    elif [[ "$DISTRO_VERSION_ID" == "6" ]]; then
        DISTRO="debian_12"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


# stop indi-allsky
if systemctl --user --quiet is-active "${ALLSKY_SERVICE_NAME}.service" >/dev/null 2>&1; then
    echo "*** Stopping indi-allsky ***"
    ALLSKY_RUNNING="true"
    systemctl --user stop "${ALLSKY_SERVICE_NAME}.service"
else
    ALLSKY_RUNNING="false"
fi


START_TIME=$(date +%s)


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.." || catch_error
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD" || catch_error


echo
echo "*** Updating code from git repo ***"
cd "$ALLSKY_DIRECTORY" || catch_error
git pull origin main


### These are the default requirements which may be overridden
VIRTUALENV_REQ=requirements/requirements_latest.txt
VIRTUALENV_REQ_OPT=requirements/requirements_optional.txt
VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
VIRTUALENV_REQ_GPIO=requirements/requirements_gpio.txt



if [[ "$DISTRO" == "debian_12" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_32.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi

elif [[ "$DISTRO" == "debian_11" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
    else
        VIRTUALENV_REQ=requirements/requirements_debian11.txt
    fi

elif [[ "$DISTRO" == "debian_10" ]]; then
    VIRTUALENV_REQ=requirements/requirements_debian10.txt
    VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt

elif [[ "$DISTRO" == "ubuntu_24.04" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_32.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi

elif [[ "$DISTRO" == "ubuntu_22.04" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    elif [ "$CPU_BITS" == "32" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_32.txt
        VIRTUALENV_REQ_POST=requirements/requirements_latest_post_32.txt
    fi

elif [[ "$DISTRO" == "ubuntu_20.04" ]]; then
    if [ "$CPU_ARCH" == "armv6l" ]; then
        VIRTUALENV_REQ=requirements/requirements_latest_armv6l.txt
        VIRTUALENV_REQ_POST=requirements/requirements_empty.txt
    else
        VIRTUALENV_REQ=requirements/requirements_debian11.txt
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


# shellcheck source=/dev/null
source "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate"

pip3 install --upgrade pip setuptools wheel packaging


PIP_REQ_ARGS=("-r" "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ}")

if [ "${OPTIONAL_PYTHON_MODULES}" == "true" ]; then
    PIP_REQ_ARGS+=("-r" "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ_OPT}")
fi

if [ "${GPIO_PYTHON_MODULES}" == "true" ]; then
    PIP_REQ_ARGS+=("-r" "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ_GPIO}")
fi

pip3 install "${PIP_REQ_ARGS[@]}"


# some modules do not have their prerequisites set
pip3 install -r "${ALLSKY_DIRECTORY}/${VIRTUALENV_REQ_POST}"


# replace rpi.gpio module with rpi.lgpio in some cases
if [ "${GPIO_PYTHON_MODULES}" == "true" ]; then
    if [[ "$DISTRO" == "debian_12" || "$DISTRO" == "ubuntu_24.04" ]]; then
        if [[ "$CPU_ARCH" == "aarch64" || "$CPU_ARCH" == "armv7l" ]]; then
            pip3 uninstall -y RPi.GPIO rpi.lgpio

            pip3 install rpi.lgpio
        fi
    fi
fi


INDI_VERSION=$(pkg-config --modversion libindi)
echo
echo
echo "Detected INDI version: $INDI_VERSION"
sleep 3


if [ "$INDI_VERSION" == "2.0.3" ]; then
    pip3 install "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.2" ]; then
    pip3 install "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.1" ]; then
    pip3 install "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.0" ]; then
    pip3 install "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "1.9.9" ]; then
    pip3 install "$PYINDI_1_9_9"
elif [ "$INDI_VERSION" == "1.9.8" ]; then
    pip3 install "$PYINDI_1_9_8"
elif [ "$INDI_VERSION" == "1.9.7" ]; then
    pip3 install "$PYINDI_1_9_8"
else
    # default to latest release
    pip3 install "$PYINDI_2_0_4"
fi


if [[ -f "${DB_FILE}" ]]; then
    echo "**** Backup DB prior to migration ****"
    DB_BACKUP="${DB_FOLDER}/backup/backup_$(date +%Y%m%d_%H%M%S).sql.gz"
    sqlite3 "${DB_FILE}" .dump | gzip -c > "$DB_BACKUP"

    chmod 640 "$DB_BACKUP"

    echo "**** Vacuum DB ****"
    sqlite3 "${DB_FILE}" "VACUUM;"
fi


cd "$ALLSKY_DIRECTORY" || catch_error
flask db revision --autogenerate
flask db upgrade head
cd "$OLDPWD" || catch_error


# some schema changes require data to be populated
echo "**** Populate database fields ****"
"${ALLSKY_DIRECTORY}/misc/populate_data.py"



# dump config for processing
TMP_CONFIG_DUMP=$(mktemp --suffix=.json)
"${ALLSKY_DIRECTORY}/config.py" dumpfile --outfile "$TMP_CONFIG_DUMP"


# final config syntax check
json_pp < "$TMP_CONFIG_DUMP" > /dev/null


# load all changes
"${ALLSKY_DIRECTORY}/config.py" load -c "$TMP_CONFIG_DUMP" --force
[[ -f "$TMP_CONFIG_DUMP" ]] && rm -f "$TMP_CONFIG_DUMP"


# final config syntax check
json_pp < "${ALLSKY_ETC}/flask.json" > /dev/null


# ensure latest code is active
systemctl --user restart "${GUNICORN_SERVICE_NAME}.service"


# restart indi-allsky
if [ "$ALLSKY_RUNNING" == "true" ]; then
    echo "*** Restarting indi-allsky ***"
    systemctl --user start "${ALLSKY_SERVICE_NAME}.service"
fi


END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo

echo
echo "Enjoy!"
