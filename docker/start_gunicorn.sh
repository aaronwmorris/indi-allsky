#!/bin/bash

set -o errexit
set -o nounset

PATH=/usr/bin:/bin
export PATH


ALLSKY_DIRECTORY=/home/allsky/indi-allsky

ALLSKY_ETC=/etc/indi-allsky


json_pp < "$ALLSKY_ETC/flask.json" >/dev/null


# start the program
cd "$ALLSKY_DIRECTORY"
"$ALLSKY_DIRECTORY/virtualenv/indi-allsky/bin/gunicorn" --config "$ALLSKY_ETC/gunicorn.conf.py" --bind 0.0.0.0:8000 indi_allsky.wsgi


