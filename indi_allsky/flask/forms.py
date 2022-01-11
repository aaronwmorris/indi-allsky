from flask_wtf import FlaskForm
#from wtforms import IntegerField
from wtforms import FloatField
from wtforms.validators import DataRequired


class IndiAllskyConfigForm(FlaskForm):
    CCD_EXPOSURE_MAX = FloatField('Exposure Max', validators=[DataRequired()])

    def __init__(self, *args, **kwargs):
        super(IndiAllskyConfigForm, self).__init__(*args, **kwargs)

