#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

PATH=/usr/bin:/bin
export PATH


ALLSKY_ETC=/etc/indi-allsky


cp -f "$ALLSKY_ETC/nginx.conf" /etc/nginx/sites-available/default
chown root:root /etc/nginx/sites-available/default
chmod 644 /etc/nginx/sites-available/default


cp -f "$ALLSKY_ETC/self-signed.key" /etc/ssl/astroberry.key
cp -f "$ALLSKY_ETC/self-signed.pem" /etc/ssl/astroberry.crt

chown root:root /etc/ssl/astroberry.key
chown root:root /etc/ssl/astroberry.crt

chmod 600 /etc/ssl/astroberry.key
chmod 644 /etc/ssl/astroberry.crt


# start nginx
/usr/sbin/nginx -g 'daemon off;'

