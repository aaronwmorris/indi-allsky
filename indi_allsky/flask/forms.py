from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms.validators import DataRequired


class IndiAllskyConfigForm(FlaskForm):
    CCD_EXPOSURE_MAX = IntegerField('Exposure Max', validators=[DataRequired()])

