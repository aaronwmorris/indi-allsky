#!/home/pi/indi-allsky/virtualenv/indi-allsky/bin/python3

#################################
# CGI interface for indi-allsky #
#                               #
# WARNING:  very slow           #
#################################

### Apache config ###
#    <Directory /home/pi>
#        Require all granted
#        Options -Indexes
#    </Directory>
#
#    <Directory /var/www/html/allsky/images>
#        Require all granted
#        Options -Indexes
#    </Directory>
#
#    # Aliases must come before ScriptAlias
#    Alias /ia/indi-allsky/images /var/www/html/allsky/images
#    Alias /ia/indi-allsky/static /home/aaron/git/indi-allsky/indi_allsky/flask/static
#
#    ScriptAlias "/ia" "/home/pi/cgi_indi-allsky.py"
#####################

### URL will be something like https://hostname/ia/indi-allsky/

import os  # noqa: F401
import sys
from wsgiref.handlers import CGIHandler


# This path needs to be where indi-allsky is installed
sys.path.append('/home/pi/indi-allsky')

# If the flask config is not located at /etc/indi-allsky/flask.json
#os.environ['INDI_ALLSKY_FLASK_CONFIG'] = '/home/pi/flask.json'


from indi_allsky.flask import create_app
application = create_app()


CGIHandler().run(application)

