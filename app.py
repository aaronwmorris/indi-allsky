### This file sets up the flask environment for the flask cli tool

from indi_allsky.flask import create_app
app = create_app()
app.app_context().push()
