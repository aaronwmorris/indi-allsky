#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset


PATH=/bin:/usr/bin
export PATH


sudo mysql -u root -e \
    "SELECT table_name, data_length, data_free \
    FROM information_schema.tables \
    WHERE table_schema='indi_allsky' \
    ORDER BY data_length DESC;"


if systemctl --user --quiet is-active indi-allsky >/dev/null 2>&1; then
    echo
    echo
    echo "ERROR: indi-allsky is running.  Please stop the service before running this script."
    echo
    exit 1
fi


echo
echo
echo "Optimizing tables in 10 seconds (control-c to cancel)"
echo
sleep 10


echo
echo
echo "Note:  Messages about tables not supporting optimize are normal"
echo

sudo mysqlcheck -u root --optimize --databases indi_allsky

