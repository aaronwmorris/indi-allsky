from flask_wtf import FlaskForm
#from wtforms import IntegerField
from wtforms import FloatField
from wtforms.validators import DataRequired
from wtforms.validators import ValidationError


def CCD_EXPOSURE_MAX_validator(form, field):
    if field.data > 60:
        raise ValidationError('Max Exposure cannot be more than 60')

    if field.data <= 0:
        raise ValidationError('Max Exposure must be more than 0')


class IndiAllskyConfigForm(FlaskForm):
    CCD_EXPOSURE_MAX = FloatField('Exposure Max', validators=[DataRequired(), CCD_EXPOSURE_MAX_validator])

    #def __init__(self, *args, **kwargs):
    #    super(IndiAllskyConfigForm, self).__init__(*args, **kwargs)

