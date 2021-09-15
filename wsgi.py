# WSGI file for mod_wsgi in apache

from indi_allsky.flask import create_app
application = create_app()
