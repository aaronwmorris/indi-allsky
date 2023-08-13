#!/home/pi/indi-allsky/virtualenv/indi-allsky/bin/python3

#################################
# CGI interface for indi-allsky #
#                               #
# WARNING:  very slow           #
#################################

### Apache config ###
# ScriptAlias "/indi-allsky" "/home/pi/cgi_indi-allsky.py"
#####################

### URL will be something like https://hostname/indi-allsky/indi-allsky/  (doubled URI)

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

