from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms import FloatField
from wtforms.validators import DataRequired
from wtforms.validators import ValidationError


def ccd_GAIN_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Gain must be more than 0')


def ccd_BINNING_validator(form, field):
    if field.data <= 0:
        raise ValidationError('Bin mode must be more than 0')

    if field.data > 4:
        raise ValidationError('Bin mode must be less than 4')


def CCD_EXPOSURE_MAX_validator(form, field):
    if field.data <= 0.0:
        raise ValidationError('Max Exposure must be more than 0')

    if field.data > 60.0:
        raise ValidationError('Max Exposure cannot be more than 60')


def CCD_EXPOSURE_DEF_validator(form, field):
    if field.data < 0.0:
        raise ValidationError('Default Exposure must be 0 or more')

    if field.data > 60.0:
        raise ValidationError('Default Exposure cannot be more than 60')


def CCD_EXPOSURE_MIN_validator(form, field):
    if field.data < 0.0:
        raise ValidationError('Minimum Exposure must be 0 or more')

    if field.data > 60.0:
        raise ValidationError('Minimum Exposure cannot be more than 60')


def EXPOSURE_PERIOD_validator(form, field):
    if field.data < 1.0:
        raise ValidationError('Exposure period must be 1.0 or more')


class IndiAllskyConfigForm(FlaskForm):
    CCD_CONFIG__NIGHT__GAIN          = IntegerField('Night Gain', validators=[DataRequired(), ccd_GAIN_validator])
    CCD_CONFIG__NIGHT__BINNING       = IntegerField('Night Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_CONFIG__MOONMODE__GAIN       = IntegerField('Moon Mode Gain', validators=[DataRequired(), ccd_GAIN_validator])
    CCD_CONFIG__MOONMODE__BINNING    = IntegerField('Moon Mode Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_CONFIG__DAY__GAIN            = IntegerField('Daytime Gain', validators=[DataRequired(), ccd_GAIN_validator])
    CCD_CONFIG__DAY__BINNING         = IntegerField('Daytime Bin Mode', validators=[DataRequired(), ccd_BINNING_validator])
    CCD_EXPOSURE_MAX                 = FloatField('Max Exposure', validators=[DataRequired(), CCD_EXPOSURE_MAX_validator])
    CCD_EXPOSURE_DEF                 = FloatField('Default Exposure', validators=[DataRequired(), CCD_EXPOSURE_DEF_validator])
    CCD_EXPOSURE_MIN                 = FloatField('Min Exposure', validators=[DataRequired(), CCD_EXPOSURE_MIN_validator])
    EXPOSURE_PERIOD                  = FloatField('Exposure Period', validators=[DataRequired(), EXPOSURE_PERIOD_validator])

    #def __init__(self, *args, **kwargs):
    #    super(IndiAllskyConfigForm, self).__init__(*args, **kwargs)

