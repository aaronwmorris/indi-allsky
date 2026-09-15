import os
from pathlib import Path
import io
import re
import json
import math
import time
from collections import OrderedDict
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import tempfile
from urllib.parse import urlparse
import psutil
import subprocess
import itertools
import dbus

from passlib.hash import argon2

from indi_allsky import constants
from indi_allsky import asi676mc
from indi_allsky import asi676mc_calibration

from flask_wtf import FlaskForm
from wtforms import IntegerField
from wtforms import FloatField
from wtforms import BooleanField
from wtforms import SelectField
from wtforms import StringField
from wtforms import PasswordField
from wtforms import TextAreaField
from wtforms import HiddenField
from wtforms import DateTimeLocalField
from wtforms import FileField
from wtforms.widgets import PasswordInput
from wtforms.widgets import NumberInput
from wtforms.validators import DataRequired
from wtforms.validators import NumberRange
#from wtforms.validators import regexp as validator_regexp
from wtforms.validators import ValidationError
from markupsafe import Markup

from sqlalchemy import extract
#from sqlalchemy import asc
from sqlalchemy import func
#from sqlalchemy.types import DateTime
#from sqlalchemy.types import Date
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import true as sa_true
from sqlalchemy.sql.expression import false as sa_false
from sqlalchemy.sql.expression import null as sa_null

from flask import current_app as app
from flask import url_for

from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbMiniVideoTable
from indi_allsky.flask.models import IndiAllSkyDbKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsVideoTable

from .validators import *
from .config_form import IndiAllskyConfigForm


from .validators import *
from .config_form import IndiAllskyConfigForm

class IndiAllskyConfigRestoreForm(FlaskForm):
    CONFIG_UPLOAD        = FileField('Config File')
    RESET_KEYS           = BooleanField('Reset Security Keys')
    FLUSH_CONFIGS        = BooleanField('Flush Configs')

    def __init__(self, *args, **kwargs):
        super(IndiAllskyConfigRestoreForm, self).__init__(*args, **kwargs)

        self.indi_allsky_config = kwargs.get('indi_allsky_config', {})


        if self.indi_allsky_config.get('ENCRYPT_PASSWORDS'):
            # changing the password key would make encrypted password unrecoverable
            self.RESET_KEYS.render_kw = {'disabled' : 'disabled'}


class IndiAllskyAsi676mcCalibrationForm(FlaskForm):
    """Small control form for the multi-file ASI676MC calibration tool.

    FITS files are intentionally represented by a normal HTML ``multiple``
    input in the template.  JavaScript transfers the selected files one at a
    time, which avoids a single huge multipart request while still requiring
    only one selection action from the user.
    """

    CAMERA_ID = SelectField(
        'ASI676MC camera',
        coerce=int,
        validators=[DataRequired()],
    )
    MAX_PAIR_SECONDS = FloatField(
        'Maximum gap between matching frames (seconds)',
        default=90.0,
        validators=[DataRequired(), NumberRange(min=1.0, max=3600.0)],
        widget=NumberInput(step=1.0),
    )
    DATABASE_GROUP_LIMIT = IntegerField(
        'Frame groups to use',
        default=20,
        validators=[NumberRange(
            min=asi676mc_calibration.DATABASE_GROUP_MIN,
            max=asi676mc_calibration.DATABASE_GROUP_MAX,
        )],
        widget=NumberInput(step=1),
    )


def _asi676mc_diagnostic_assets(images, camera_id, s3_prefix, local):
    """Resolve diagnostic triplets for image-viewer download controls."""
    selected_pairs = {}
    capture_ids = set()

    for img in images:
        image_metadata = img.data or {}
        diagnostic_metadata = image_metadata.get(
            'asi676mc_diagnostic_fits',
            {},
        )
        roles = diagnostic_metadata.get('roles', [])
        if not roles:
            continue

        repair_status = image_metadata.get('asi676mc_repair_status')
        preferred_roles = (
            ('bad',)
            if repair_status in asi676mc.DIAGNOSTIC_BAD_STATUSES
            # A normal frame can be the following reference for one failure
            # and the preceding reference for the next. Prefer the latter
            # triplet when choosing the one capture shown on that image row;
            # each purple image still exposes its own complete group.
            else ('preceding', 'following')
        )
        selected_role = next(
            (
                role
                for preferred_role in preferred_roles
                for role in roles
                if role.get('role') == preferred_role
            ),
            roles[0],
        )
        capture_id = selected_role.get('capture_id')
        if not capture_id:
            continue

        selected_pairs[img.id] = capture_id
        capture_ids.add(capture_id)

    if not capture_ids:
        return {}

    image_dates = [img.createDate for img in images]
    query_start = min(image_dates) - timedelta(minutes=15)
    query_stop = max(image_dates) + timedelta(minutes=15)
    fits_entries = IndiAllSkyDbFitsImageTable.query\
        .filter(IndiAllSkyDbFitsImageTable.camera_id == camera_id)\
        .filter(IndiAllSkyDbFitsImageTable.createDate >= query_start)\
        .filter(IndiAllSkyDbFitsImageTable.createDate <= query_stop)\
        .order_by(IndiAllSkyDbFitsImageTable.createDate.asc())\
        .all()

    pair_assets = {}
    for fits_entry in fits_entries:
        diagnostic_metadata = (fits_entry.data or {}).get(
            asi676mc.DIAGNOSTIC_METADATA_KEY,
            {},
        )
        for role in diagnostic_metadata.get('roles', []):
            capture_id = role.get('capture_id')
            role_name = role.get('role')
            if (
                capture_id not in capture_ids
                or role_name not in ('preceding', 'bad', 'following')
            ):
                continue

            if (
                not local
                and not fits_entry.remote_url
                and not fits_entry.s3_key
            ):
                continue

            try:
                fits_url = fits_entry.getUrl(
                    s3_prefix=s3_prefix,
                    local=local,
                )
            except ValueError as e:
                app.logger.error(
                    'Error determining diagnostic FITS URL: %s',
                    str(e),
                )
                continue

            pair_assets.setdefault(capture_id, {})[role_name] = {
                'url': str(fits_url),
                'filename': Path(fits_entry.filename).name,
            }

    image_assets = {}
    for image_id, capture_id in selected_pairs.items():
        assets = pair_assets.get(capture_id, {})
        image_assets[image_id] = {
            'preceding': assets.get('preceding'),
            'bad': assets.get('bad'),
            'following': assets.get('following'),
        }

    return image_assets


class IndiAllskyTimelapseGeneratorForm_old(FlaskForm):
    # to be deleted
    ACTION_SELECT_choices = (
        ('none', '(Please select an action)'),
        ('generate_video_k_st', 'Generate All'),
        ('generate_video', 'Generate Timelapse Only'),
        ('generate_k_st', 'Generate Keogram/Star Trails'),
        ('generate_panorama_video', 'Generate Panorama Timelapse'),
        ('delete_video_k_st_p', 'Delete Timelapse/Keogram/Star Trails/Panorama'),
        ('delete_video', 'Delete Timelapse Only'),
        ('delete_k_st', 'Delete Keogram/Star Trails'),
        ('delete_panorama_video', 'Delete Panorama Timelapse'),
        ('upload_endofnight', 'Upload End-of-Night Data [today only]'),
        ('delete_images', 'Delete Images for date *DANGER*'),
    )

    CAMERA_ID          = HiddenField('Camera ID', validators=[DataRequired()])
    ACTION_SELECT      = SelectField('Action', choices=ACTION_SELECT_choices, validators=[DataRequired()])
    DAY_SELECT         = SelectField('Day', choices=[], validators=[DataRequired()])
    CONFIRM1           = BooleanField('Confirm')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyTimelapseGeneratorForm, self).__init__(*args, **kwargs)

        self.camera_id = kwargs['camera_id']

        dates_start = time.time()

        self.DAY_SELECT.choices = self.getDistinctDays(self.camera_id)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


    def getDistinctDays(self, camera_id):
        dayDate_day = func.distinct(IndiAllSkyDbImageTable.dayDate).label('day')

        days_query = db.session.query(
            dayDate_day
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .order_by(IndiAllSkyDbImageTable.dayDate.desc())


        day_list = list()
        for entry in days_query:
            # cannot query from inside a query
            if db.engine.dialect.name == 'mysql':
                # mysql returns a date object
                day_list.append(entry.day)
            else:
                # sqlite returns a string
                day_list.append(datetime.strptime(entry.day, '%Y-%m-%d').date())


        day_choices = list()
        for day_date in day_list:
            day_str = day_date.strftime('%Y-%m-%d')

            day_night_str = '{0:s} Night'.format(day_str)
            day_day_str = '{0:s} Day'.format(day_str)


            # videos
            video_entry_night = IndiAllSkyDbVideoTable.query\
                .join(IndiAllSkyDbVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbVideoTable.dayDate == day_date,
                        IndiAllSkyDbVideoTable.night == sa_true(),
                    )
                )\
                .first()

            if video_entry_night:
                if not video_entry_night.success:
                    day_night_str = '{0:s} [!T]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [T]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            video_entry_day = IndiAllSkyDbVideoTable.query\
                .join(IndiAllSkyDbVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbVideoTable.dayDate == day_date,
                        IndiAllSkyDbVideoTable.night == sa_false(),
                    )
                )\
                .first()

            if video_entry_day:
                if not video_entry_day.success:
                    day_day_str = '{0:s} [!T]'.format(day_day_str)
                else:
                    day_day_str = '{0:s} [T]'.format(day_day_str)
            else:
                day_day_str = '{0:s} [ ]'.format(day_day_str)


            # keogram
            keogram_entry_night = IndiAllSkyDbKeogramTable.query\
                .join(IndiAllSkyDbKeogramTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbKeogramTable.dayDate == day_date,
                        IndiAllSkyDbKeogramTable.night == sa_true(),
                    )
                )\
                .first()

            if keogram_entry_night:
                if not keogram_entry_night.success:
                    day_night_str = '{0:s} [!K]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [K]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            keogram_entry_day = IndiAllSkyDbKeogramTable.query\
                .join(IndiAllSkyDbKeogramTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbKeogramTable.dayDate == day_date,
                        IndiAllSkyDbKeogramTable.night == sa_false(),
                    )
                )\
                .first()

            if keogram_entry_day:
                if not keogram_entry_day.success:
                    day_day_str = '{0:s} [!K]'.format(day_day_str)
                else:
                    day_day_str = '{0:s} [K]'.format(day_day_str)
            else:
                day_day_str = '{0:s} [ ]'.format(day_day_str)


            # star trail
            startrail_entry_night = IndiAllSkyDbStarTrailsTable.query\
                .join(IndiAllSkyDbStarTrailsTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbStarTrailsTable.dayDate == day_date,
                        IndiAllSkyDbStarTrailsTable.night == sa_true(),
                    )
                )\
                .first()

            if startrail_entry_night:
                if not startrail_entry_night.success:
                    day_night_str = '{0:s} [!S]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [S]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            # star trail video
            startrail_video_entry_night = IndiAllSkyDbStarTrailsVideoTable.query\
                .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbStarTrailsVideoTable.dayDate == day_date,
                        IndiAllSkyDbStarTrailsVideoTable.night == sa_true(),
                    )
                )\
                .first()

            if startrail_video_entry_night:
                if not startrail_video_entry_night.success:
                    day_night_str = '{0:s} [!ST]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [ST]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            # panorama video
            panorama_video_entry_night = IndiAllSkyDbPanoramaVideoTable.query\
                .join(IndiAllSkyDbPanoramaVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbPanoramaVideoTable.dayDate == day_date,
                        IndiAllSkyDbPanoramaVideoTable.night == sa_true(),
                    )
                )\
                .first()

            if panorama_video_entry_night:
                if not panorama_video_entry_night.success:
                    day_night_str = '{0:s} [!P]'.format(day_night_str)
                else:
                    day_night_str = '{0:s} [P]'.format(day_night_str)
            else:
                day_night_str = '{0:s} [ ]'.format(day_night_str)


            panorama_video_entry_day = IndiAllSkyDbPanoramaVideoTable.query\
                .join(IndiAllSkyDbPanoramaVideoTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbPanoramaVideoTable.dayDate == day_date,
                        IndiAllSkyDbPanoramaVideoTable.night == sa_false(),
                    )
                )\
                .first()

            if panorama_video_entry_day:
                if not panorama_video_entry_day.success:
                    day_day_str = '{0:s} [!P]'.format(day_day_str)
                else:
                    day_day_str = '{0:s} [P]'.format(day_day_str)
            else:
                day_day_str = '{0:s} [ ]'.format(day_day_str)


            # images
            images_night = IndiAllSkyDbImageTable.query\
                .join(IndiAllSkyDbImageTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbImageTable.dayDate == day_date,
                        IndiAllSkyDbImageTable.night == sa_true(),
                    )
                )

            panorama_night = IndiAllSkyDbPanoramaImageTable.query\
                .join(IndiAllSkyDbPanoramaImageTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbPanoramaImageTable.dayDate == day_date,
                        IndiAllSkyDbPanoramaImageTable.night == sa_true(),
                    )
                )


            day_night_str = '{0:s} - {1:d}/{2:d} images'.format(day_night_str, images_night.count(), panorama_night.count())


            images_day = IndiAllSkyDbImageTable.query\
                .join(IndiAllSkyDbImageTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbImageTable.dayDate == day_date,
                        IndiAllSkyDbImageTable.night == sa_false(),
                    )
                )

            panorama_day = IndiAllSkyDbPanoramaImageTable.query\
                .join(IndiAllSkyDbPanoramaImageTable.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera_id,
                        IndiAllSkyDbPanoramaImageTable.dayDate == day_date,
                        IndiAllSkyDbPanoramaImageTable.night == sa_false(),
                    )
                )

            day_day_str = '{0:s} - {1:d}/{2:d} images'.format(day_day_str, images_day.count(), panorama_day.count())


            entry_night = ('{0:s}_night'.format(day_str), day_night_str)
            day_choices.append(entry_night)

            entry_day = ('{0:s}_day'.format(day_str), day_day_str)
            day_choices.append(entry_day)

        return day_choices


class IndiAllskyTimelapseGeneratorForm(FlaskForm):
    ACTION_SELECT_choices = (
        ('none', '(Please select an action)'),
        ('generate_video_k_st', 'Generate All'),
        ('generate_video', 'Generate Timelapse Only'),
        ('generate_k_st', 'Generate Keogram/Star Trails'),
        ('generate_panorama_video', 'Generate Panorama Timelapse'),
        ('delete_video_k_st_p', 'Delete Timelapse/Keogram/Star Trails/Panorama'),
        ('delete_video', 'Delete Timelapse Only'),
        ('delete_k_st', 'Delete Keogram/Star Trails'),
        ('delete_panorama_video', 'Delete Panorama Timelapse'),
        ('upload_endofnight', 'Upload End-of-Night Data [today only]'),
        ('delete_images', 'Delete Images for date *DANGER*'),
    )

    CAMERA_ID          = HiddenField('Camera ID', validators=[DataRequired()])
    ACTION_SELECT      = SelectField('Action', choices=ACTION_SELECT_choices, validators=[DataRequired()])
    DAY_SELECT         = SelectField('Day', choices=[], validators=[DataRequired()])
    CONFIRM1           = BooleanField('Confirm')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyTimelapseGeneratorForm, self).__init__(*args, **kwargs)

        self.camera_id = kwargs['camera_id']

        dates_start = time.time()

        self.DAY_SELECT.choices = self.getDistinctDays(self.camera_id)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


    def getDistinctDays(self, camera_id):

        ### get image count
        # this is 10x slower on mysql vs sqlite
        # still acceptable performance
        days_query_images = db.session.query(
            func.distinct(IndiAllSkyDbImageTable.dayDate).label('dayDate_distinct'),
            IndiAllSkyDbImageTable.night,
            func.count(IndiAllSkyDbImageTable.id).label('image_count'),
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .group_by(IndiAllSkyDbImageTable.dayDate, IndiAllSkyDbImageTable.night)\
            .order_by(IndiAllSkyDbImageTable.dayDate.desc())



        day_dict = OrderedDict()
        for entry in days_query_images:
            if db.engine.dialect.name == 'mysql':
                # mysql returns a date object
                dayDate = entry.dayDate_distinct
            else:
                # sqlite returns a string
                dayDate = datetime.strptime(entry.dayDate_distinct, '%Y-%m-%d').date()

            if not day_dict.get(dayDate):
                day_dict[dayDate] = OrderedDict({
                    'Night' : {
                        'image_count' : 0,
                        'panoramaimage_count' : 0,
                        'night' : True,
                        'dayDate' : dayDate,
                    },
                    'Day' : {
                        'image_count' : 0,
                        'panoramaimage_count' : 0,
                        'night' : False,
                        'dayDate' : dayDate,
                    },
                })

            if entry.night:
                day_dict[dayDate]['Night']['image_count'] = entry.image_count
            else:
                day_dict[dayDate]['Day']['image_count'] = entry.image_count


        ### get parorama count
        # this is 10x slower on mysql vs sqlite
        # still acceptable performance
        days_query_panorama_images = db.session.query(
            func.distinct(IndiAllSkyDbPanoramaImageTable.dayDate).label('dayDate_distinct'),
            IndiAllSkyDbPanoramaImageTable.night,
            func.count(IndiAllSkyDbPanoramaImageTable.id).label('image_count'),
        )\
            .join(IndiAllSkyDbPanoramaImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .group_by(IndiAllSkyDbPanoramaImageTable.dayDate, IndiAllSkyDbPanoramaImageTable.night)\
            .order_by(IndiAllSkyDbPanoramaImageTable.dayDate.desc())


        for entry in days_query_panorama_images:
            if db.engine.dialect.name == 'mysql':
                # mysql returns a date object
                dayDate = entry.dayDate_distinct
            else:
                # sqlite returns a string
                dayDate = datetime.strptime(entry.dayDate_distinct, '%Y-%m-%d').date()


            if not day_dict.get(dayDate):
                day_dict[dayDate] = OrderedDict({
                    'Night' : {
                        'image_count' : 0,
                        'panoramaimage_count' : 0,
                        'night' : sa_true(),
                        'dayDate' : dayDate,
                    },
                    'Day' : {
                        'image_count' : 0,
                        'panoramaimage_count' : 0,
                        'night' : sa_false(),
                        'dayDate' : dayDate,
                    },
                })


            if entry.night:
                day_dict[dayDate]['Night']['panoramaimage_count'] = entry.image_count
            else:
                day_dict[dayDate]['Day']['panoramaimage_count'] = entry.image_count


        # Build choices
        day_choices = list()
        for k, tod_dict in day_dict.items():
            for tod, entry in tod_dict.items():
                if tod == 'Night':
                    day_str = '{0:%Y-%m-%d} Night'.format(entry['dayDate'])
                else:
                    day_str = '{0:%Y-%m-%d} Day'.format(entry['dayDate'])


                # videos
                video_entry = IndiAllSkyDbVideoTable.query\
                    .join(IndiAllSkyDbVideoTable.camera)\
                    .filter(
                        and_(
                            IndiAllSkyDbCameraTable.id == camera_id,
                            IndiAllSkyDbVideoTable.dayDate == entry['dayDate'],
                            IndiAllSkyDbVideoTable.night == entry['night'],
                        )
                    )\
                    .first()

                if video_entry:
                    if not video_entry.success:
                        day_str = '{0:s} [!T]'.format(day_str)
                    else:
                        day_str = '{0:s} [T]'.format(day_str)
                else:
                    day_str = '{0:s} [ ]'.format(day_str)


                # keogram
                keogram_entry = IndiAllSkyDbKeogramTable.query\
                    .join(IndiAllSkyDbKeogramTable.camera)\
                    .filter(
                        and_(
                            IndiAllSkyDbCameraTable.id == camera_id,
                            IndiAllSkyDbKeogramTable.dayDate == entry['dayDate'],
                            IndiAllSkyDbKeogramTable.night == entry['night'],
                        )
                    )\
                    .first()

                if keogram_entry:
                    if not keogram_entry.success:
                        day_str = '{0:s} [!K]'.format(day_str)
                    else:
                        day_str = '{0:s} [K]'.format(day_str)
                else:
                    day_str = '{0:s} [ ]'.format(day_str)


                # panorama video
                panorama_video_entry = IndiAllSkyDbPanoramaVideoTable.query\
                    .join(IndiAllSkyDbPanoramaVideoTable.camera)\
                    .filter(
                        and_(
                            IndiAllSkyDbCameraTable.id == camera_id,
                            IndiAllSkyDbPanoramaVideoTable.dayDate == entry['dayDate'],
                            IndiAllSkyDbPanoramaVideoTable.night == entry['night'],
                        )
                    )\
                    .first()

                if panorama_video_entry:
                    if not panorama_video_entry.success:
                        day_str = '{0:s} [!P]'.format(day_str)
                    else:
                        day_str = '{0:s} [P]'.format(day_str)
                else:
                    day_str = '{0:s} [ ]'.format(day_str)


                # star trail
                if tod == 'Night':
                    startrail_entry = IndiAllSkyDbStarTrailsTable.query\
                        .join(IndiAllSkyDbStarTrailsTable.camera)\
                        .filter(
                            and_(
                                IndiAllSkyDbCameraTable.id == camera_id,
                                IndiAllSkyDbStarTrailsTable.dayDate == entry['dayDate'],
                                IndiAllSkyDbStarTrailsTable.night == entry['night'],
                            )
                        )\
                        .first()

                    if startrail_entry:
                        if not startrail_entry.success:
                            day_str = '{0:s} [!S]'.format(day_str)
                        else:
                            day_str = '{0:s} [S]'.format(day_str)
                    else:
                        day_str = '{0:s} [ ]'.format(day_str)


                    # star trail video
                    startrail_video_entry = IndiAllSkyDbStarTrailsVideoTable.query\
                        .join(IndiAllSkyDbStarTrailsVideoTable.camera)\
                        .filter(
                            and_(
                                IndiAllSkyDbCameraTable.id == camera_id,
                                IndiAllSkyDbStarTrailsVideoTable.dayDate == entry['dayDate'],
                                IndiAllSkyDbStarTrailsVideoTable.night == entry['night'],
                            )
                        )\
                        .first()

                    if startrail_video_entry:
                        if not startrail_video_entry.success:
                            day_str = '{0:s} [!ST]'.format(day_str)
                        else:
                            day_str = '{0:s} [ST]'.format(day_str)
                    else:
                        day_str = '{0:s} [ ]'.format(day_str)


                day_str = '{0:s} - {1:d}/{2:d} images'.format(day_str, entry['image_count'], entry['panoramaimage_count'])


                if tod == 'Night':
                    entry_night = ('{0:%Y-%m-%d}_night'.format(entry['dayDate']), day_str)
                    day_choices.append(entry_night)
                else:
                    entry_day = ('{0:%Y-%m-%d}_day'.format(entry['dayDate']), day_str)
                    day_choices.append(entry_day)

        return day_choices


class IndiAllskySystemInfoForm(FlaskForm):
    # fake form to send commands to web application

    CAMERA_ID           = HiddenField('Camera ID', validators=[DataRequired()])
    SERVICE_HIDDEN      = HiddenField('service_hidden', validators=[DataRequired()])
    COMMAND_HIDDEN      = HiddenField('command_hidden', validators=[DataRequired()])


class IndiAllskyLoopHistoryForm(FlaskForm):
    HISTORY_SELECT_choices = (
        ('900', '15 Minutes'),
        ('1800', '30 Minutes'),
        ('2700', '45 Minutes'),
        ('3600', '1 Hour'),
        ('7200', '2 Hours'),
        ('10800', '3 Hours'),
        ('14400', '4 Hours'),
    )

    FRAMEDELAY_SELECT_choices = (
        ('20', '50 FPS'),
        ('40', '25 FPS'),
        ('100', '10 FPS'),
        ('200', '5 FPS'),
    )

    HISTORY_SELECT       = SelectField('History', choices=HISTORY_SELECT_choices, default=HISTORY_SELECT_choices[0][0], validators=[])
    FRAMEDELAY_SELECT    = SelectField('Speed', choices=FRAMEDELAY_SELECT_choices, default=FRAMEDELAY_SELECT_choices[2][0], validators=[])
    ROCK_CHECKBOX        = BooleanField('Rock', default=False)


class IndiAllskyChartHistoryForm(FlaskForm):
    HISTORY_SELECT_choices = (
        ('900', '15 Minutes'),
        ('1800', '30 Minutes'),
        ('2700', '45 Minutes'),
        ('3600', '1 Hour'),
        ('7200', '2 Hours'),
        ('10800', '3 Hours'),
        ('14400', '4 Hours'),
        ('21600', '6 Hours'),
        ('43200', '12 Hours'),
        ('86400', '24 Hours'),
    )

    HISTORY_SELECT       = SelectField('History', choices=HISTORY_SELECT_choices, default=HISTORY_SELECT_choices[0][0], validators=[])


class IndiAllskySetDateTimeForm(FlaskForm):

    NEW_DATETIME = DateTimeLocalField('New Datetime', render_kw={'step' : '1'}, format='%Y-%m-%dT%H:%M:%S', validators=[DataRequired()])


class IndiAllskySetTimezoneForm(FlaskForm):

    NEW_TIMEZONE = SelectField('New Timezone', validators=[DataRequired()])


    def __init__(self, *args, **kwargs):
        super(IndiAllskySetTimezoneForm, self).__init__(*args, **kwargs)

        self.NEW_TIMEZONE.choices = self.getSystemdTimezones()


    def getSystemdTimezones(self):
        try:
            session_bus = dbus.SystemBus()
        except dbus.exceptions.DBusException:
            return (['D-Bus Unavailable', 'D-Bus Unavailable'],)


        timedate1 = session_bus.get_object('org.freedesktop.timedate1', '/org/freedesktop/timedate1')
        manager = dbus.Interface(timedate1, 'org.freedesktop.timedate1')

        systemd_timezones = manager.ListTimezones()

        #app.logger.info('Timezones: %s', timezone_list)


        timezone_list = list()
        for tz in systemd_timezones:
            timezone_list.append([str(tz), str(tz)])


        # ensure sorted by name
        timezone_list_sorted = sorted(timezone_list, key=lambda x: x[0])


        return timezone_list_sorted


class IndiAllskyFocusForm(FlaskForm):
    ZOOM_SELECT_choices = (
        (2, 'Off'),
        (5, 'Low'),
        (10, 'Medium'),
        (20, 'High'),
        (40, 'Extreme'),
        (60, 'Ridiculous'),
        (80, 'Ludicrous'),
        (100, 'Plaid'),
    )
    REFRESH_SELECT_choices = (
        (2, '2s'),
        (3, '3s'),
        (4, '4s'),
        (5, '5s'),
        (10, '10s'),
        (15, '15s'),
    )


    ZOOM_SELECT       = SelectField('Zoom', choices=ZOOM_SELECT_choices, default=ZOOM_SELECT_choices[0][0], validators=[])
    REFRESH_SELECT    = SelectField('Refresh', choices=REFRESH_SELECT_choices, default=REFRESH_SELECT_choices[3][0], validators=[])
    X_OFFSET          = IntegerField('X Offset', default=0)
    Y_OFFSET          = IntegerField('Y Offset', default=0)


class IndiAllskyCameraSelectForm(FlaskForm):
    CAMERA_SELECT     = SelectField('CAMERA', validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyCameraSelectForm, self).__init__(*args, **kwargs)

        self.CAMERA_SELECT.choices = self.getCameras()


    def getCameras(self):
        cameras = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
            .order_by(IndiAllSkyDbCameraTable.id.asc())

        camera_list = list()
        for camera in cameras:
            if camera.friendlyName:
                camera_name = camera.friendlyName
            else:
                camera_name = camera.name

            camera_list.append((camera.id, camera_name))

        return camera_list


class IndiAllskyImageExcludeForm(FlaskForm):
    EXCLUDE_IMAGE_ID    = HiddenField('Image ID', validators=[DataRequired()])
    EXCLUDE_EXCLUDE     = BooleanField('Exclude Image From Timelapse', render_kw={'disabled' : 'disabled'})  # enabled in template


    def __init__(self, *args, **kwargs):
        super(IndiAllskyImageExcludeForm, self).__init__(*args, **kwargs)


class IndiAllskyFocusControllerForm(FlaskForm):
    STEP_DEGREES_choices = (
        (6, '6 degrees'),
        (12, '12 Degrees'),
        (24, '24 Degrees'),
        (45, '45 Degrees'),
        (90, '90 Degrees'),
        (180, '180 Degrees'),
    )

    DIRECTION           = StringField('Direction')
    STEP_DEGREES        = SelectField('Degrees', choices=STEP_DEGREES_choices, default=STEP_DEGREES_choices[2][0], validators=[])


class IndiAllskyImageProcessingForm(FlaskForm):

    CFA_PATTERN_choices = IndiAllskyConfigForm.CFA_PATTERN_choices
    IMAGE_COLORMAP_choices = IndiAllskyConfigForm.IMAGE_COLORMAP_choices
    SCNR_ALGORITHM_choices = IndiAllskyConfigForm.SCNR_ALGORITHM_choices
    IMAGE_DENOISE_choices = IndiAllskyConfigForm.IMAGE_DENOISE_choices
    TEXT_PROPERTIES__PIL_FONT_FILE_choices = IndiAllskyConfigForm.TEXT_PROPERTIES__PIL_FONT_FILE_choices


    OUTPUT_IMAGE_TYPE_choices = (
        ('jpg', 'JPEG'),
        ('png', 'PNG'),
    )

    DISABLE_PROCESSING               = BooleanField('Disable processing')
    OUTPUT_IMAGE_TYPE                = SelectField('Output Type', choices=OUTPUT_IMAGE_TYPE_choices, validators=[DataRequired()])
    CAMERA_ID                        = HiddenField('Camera ID', validators=[DataRequired()])
    FRAME_TYPE                       = HiddenField('FRAME_TYPE', validators=[DataRequired()])
    FITS_ID                          = HiddenField('FITS ID', validators=[DataRequired()])
    LENS_IMAGE_CIRCLE                = IntegerField('Image Circle', validators=[LENS_IMAGE_CIRCLE_validator])
    LENS_OFFSET_X                    = IntegerField('Lens X Offset', validators=[LENS_OFFSET_validator])
    LENS_OFFSET_Y                    = IntegerField('Lens Y Offset', validators=[LENS_OFFSET_validator])
    LENS_AZIMUTH                     = FloatField('Azimuth', validators=[LENS_AZIMUTH_validator])
    IMAGE_CALIBRATE_DARK             = BooleanField('Dark Frame Calibration')
    IMAGE_CALIBRATE_BPM              = BooleanField('Bad Pixel Map Calibration')
    IMAGE_CALIBRATE_MANUAL_OFFSET    = IntegerField('Manual Offset', validators=[IMAGE_CALIBRATE_MANUAL_OFFSET_validator])
    IMAGE_CALIBRATE_FIX_HOLES        = BooleanField('Fix Calibration Holes')
    IMAGE_CALIBRATE_HOLE_THOLD       = IntegerField('Hole ADU Threshold %', validators=[IMAGE_CALIBRATE_HOLE_THOLD_validator])
    CCD_BIT_DEPTH                    = SelectField('Camera Bit Depth', choices=IndiAllskyConfigForm.CCD_BIT_DEPTH_choices, validators=[CCD_BIT_DEPTH_validator])
    NIGHT_CONTRAST_ENHANCE           = BooleanField('Contrast Enhance')
    CONTRAST_ENHANCE_16BIT           = BooleanField('16-bit Contrast Enhance')
    CLAHE_CLIPLIMIT                  = FloatField('CLAHE Clip Limit', validators=[CLAHE_CLIPLIMIT_validator])
    CLAHE_GRIDSIZE                   = IntegerField('CLAHE Grid Size', validators=[CLAHE_GRIDSIZE_validator])
    IMAGE_STRETCH__CLASSNAME         = SelectField('Stretch Function', choices=IndiAllskyConfigForm.IMAGE_STRETCH__CLASSNAME_choices, validators=[IMAGE_STRETCH__CLASSNAME_validator])
    IMAGE_STRETCH__MODE1_GAMMA       = FloatField('Stretching Gamma', validators=[IMAGE_STRETCH__MODE1_GAMMA_validator])
    IMAGE_STRETCH__MODE1_STDDEVS     = FloatField('Stretching Std Deviations', validators=[DataRequired(), IMAGE_STRETCH__MODE1_STDDEVS_validator])
    IMAGE_STRETCH__MODE2_SHADOWS     = FloatField('MTF - Shadows Cutoff', validators=[IMAGE_STRETCH__MODE2_SHADOWS_validator])
    IMAGE_STRETCH__MODE2_MIDTONES    = FloatField('MTF - Midtones Target', validators=[IMAGE_STRETCH__MODE2_MIDTONES_validator])
    IMAGE_STRETCH__MODE2_HIGHLIGHTS  = FloatField('MTF - Highlights Cutoff', validators=[IMAGE_STRETCH__MODE2_HIGHLIGHTS_validator])
    IMAGE_STRETCH__MODE3_BLACK_CLIP  = FloatField('Adaptive MTF - Black Clip', validators=[IMAGE_STRETCH__MODE3_BLACK_CLIP_validator])
    IMAGE_STRETCH__MODE3_SHADOWS     = FloatField('Adaptive MTF - Shadows Cutoff', validators=[IMAGE_STRETCH__MODE3_SHADOWS_validator])
    IMAGE_STRETCH__MODE3_MIDTONES    = FloatField('Adaptive MTF - Midtones Target', validators=[IMAGE_STRETCH__MODE3_MIDTONES_validator])
    IMAGE_STRETCH__MODE3_HIGHLIGHTS  = FloatField('Adaptive MTF - Highlights Cutoff', validators=[IMAGE_STRETCH__MODE3_HIGHLIGHTS_validator])
    #IMAGE_STRETCH__SPLIT            = BooleanField('Stretching split screen')
    CFA_PATTERN                      = SelectField('Bayer Pattern', choices=CFA_PATTERN_choices, validators=[CFA_PATTERN_validator])
    SCNR_ALGORITHM                   = SelectField('SCNR (green reduction)', choices=IndiAllskyConfigForm.SCNR_ALGORITHM_choices, validators=[SCNR_ALGORITHM_validator])
    SCNR_MTF_MIDTONES                = FloatField('SCNR MTF Midtones', validators=[SCNR_MTF_MIDTONES_validator])
    IMAGE_DENOISE                    = SelectField('Denoise', choices=IndiAllskyConfigForm.IMAGE_DENOISE_choices, validators=[IMAGE_DENOISE_validator])
    IMAGE_DENOISE_STRENGTH           = IntegerField('Denoise Strength', validators=[IMAGE_DENOISE_STRENGTH_validator], widget=NumberInput(step=1))
    BILATERAL_SIGMA_COLOR            = IntegerField('Bilateral Sigma Color', validators=[BILATERAL_SIGMA_validator], widget=NumberInput(step=1))
    BILATERAL_SIGMA_SPACE            = IntegerField('Bilateral Sigma Space', validators=[BILATERAL_SIGMA_validator], widget=NumberInput(step=1))
    WBR_FACTOR                       = FloatField('Red Balance Factor', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    WBG_FACTOR                       = FloatField('Green Balance Factor', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    WBB_FACTOR                       = FloatField('Blue Balance Factor', validators=[WB_FACTOR_validator], widget=NumberInput(step=0.01))
    AUTO_WB                          = BooleanField('Auto White Balance')
    WBR_MTF_MIDTONES                 = FloatField('Red Balance MTF Midtones', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    WBG_MTF_MIDTONES                 = FloatField('Green Balance MTF Midtones', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    WBB_MTF_MIDTONES                 = FloatField('Blue Balance MTF Midtones', validators=[WB_MTF_MIDTONES_validator], widget=NumberInput(step=0.01))
    SATURATION_FACTOR                = FloatField('Saturation Factor', validators=[SATURATION_FACTOR_validator], widget=NumberInput(step=0.01))
    GAMMA_CORRECTION                 = FloatField('Gamma Correction', validators=[GAMMA_CORRECTION_validator], widget=NumberInput(step=0.01))
    SHARPEN_AMOUNT                   = FloatField('Sharpen Amount', validators=[SHARPEN_AMOUNT_validator], widget=NumberInput(step=0.01))
    IMAGE_ROTATE                     = SelectField('Rotate Image', choices=IndiAllskyConfigForm.IMAGE_ROTATE_choices, validators=[IMAGE_ROTATE_validator])
    IMAGE_ROTATE_ANGLE               = IntegerField('Rotation Angle', validators=[IMAGE_ROTATE_ANGLE_validator])
    IMAGE_ROTATE_KEEP_SIZE           = BooleanField('Maintain Size After Rotation')
    IMAGE_FLIP_V                     = BooleanField('Flip Image Vertically')
    IMAGE_FLIP_H                     = BooleanField('Flip Image Horizontally')
    IMAGE_COLORMAP                   = SelectField('Apply Colormap', choices=IMAGE_COLORMAP_choices, validators=[IMAGE_COLORMAP_validator])
    DETECT_MASK                      = StringField('Detection Mask', validators=[DETECT_MASK_validator])
    DETECT_STARS_METHOD_choices = IndiAllskyConfigForm.DETECT_STARS_METHOD_choices

    RUN_DETECTION                    = BooleanField('Run Detection')
    DETECT_STARS_METHOD              = SelectField('Star Detection Method', choices=DETECT_STARS_METHOD_choices)
    DETECT_STARS_THOLD               = FloatField('Star Detection Threshold', validators=[DETECT_STARS_THOLD_validator], widget=NumberInput(step=0.01))
    DETECT_STARS_SEP_THOLD           = FloatField('Star Sigma Threshold', validators=[DETECT_STARS_SEP_THOLD_validator], widget=NumberInput(step=0.5))
    DETECT_STARS_SEP_MAX_RADIUS      = IntegerField('SEP Max Star Radius', validators=[DETECT_STARS_SEP_MAX_RADIUS_validator])
    DETECT_METEORS_THOLD             = IntegerField('Meteor Detection Threshold', validators=[DETECT_METEORS_THOLD_validator])
    SQM_ROI_X1                       = IntegerField('SQM ROI x1', validators=[SQM_ROI_validator])
    SQM_ROI_Y1                       = IntegerField('SQM ROI y1', validators=[SQM_ROI_validator])
    SQM_ROI_X2                       = IntegerField('SQM ROI x2', validators=[SQM_ROI_validator])
    SQM_ROI_Y2                       = IntegerField('SQM ROI y2', validators=[SQM_ROI_validator])
    SQM_FOV_DIV                      = SelectField('SQM FoV', choices=IndiAllskyConfigForm.SQM_FOV_DIV_choices, validators=[SQM_FOV_DIV_validator])
    IMAGE_STACK_METHOD               = SelectField('Image stacking method', choices=IndiAllskyConfigForm.IMAGE_STACK_METHOD_choices, validators=[DataRequired(), IMAGE_STACK_METHOD_validator])
    IMAGE_STACK_COUNT                = SelectField('Stack count', choices=IndiAllskyConfigForm.IMAGE_STACK_COUNT_choices, validators=[DataRequired(), IMAGE_STACK_COUNT_validator])
    IMAGE_STACK_ALIGN                = BooleanField('Register images')
    IMAGE_ALIGN_DETECTSIGMA          = IntegerField('Alignment sensitivity', validators=[DataRequired(), IMAGE_ALIGN_DETECTSIGMA_validator])
    IMAGE_ALIGN_POINTS               = IntegerField('Alignment points', validators=[DataRequired(), IMAGE_ALIGN_POINTS_validator])
    IMAGE_ALIGN_SOURCEMINAREA        = IntegerField('Minimum point area', validators=[DataRequired(), IMAGE_ALIGN_SOURCEMINAREA_validator])
    FISH2PANO__ENABLE                = BooleanField('Fisheye to Panoramic')
    FISH2PANO__DIAMETER              = IntegerField('Diameter', validators=[DataRequired(), FISH2PANO__DIAMETER_validator])
    FISH2PANO__ROTATE_ANGLE          = IntegerField('Rotation Angle', validators=[FISH2PANO__ROTATE_ANGLE_validator])
    FISH2PANO__SCALE                 = FloatField('Scale', validators=[FISH2PANO__SCALE_validator])
    FISH2PANO__FLIP_H                = BooleanField('Flip Horizontally')
    FISH2PANO__ENABLE_CARDINAL_DIRS  = BooleanField('Panorama Cardinal Directions')
    FISH2PANO__DIRS_OFFSET_BOTTOM    = IntegerField('Label Bottom Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    FISH2PANO__OPENCV_FONT_SCALE     = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    FISH2PANO__PIL_FONT_SIZE         = IntegerField('Font Size (pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    #IMAGE_STACK_SPLIT                = BooleanField('Stack split screen')
    PROCESSING_SPLIT_SCREEN          = BooleanField('Split screen')
    IMAGE_LABEL_TEMPLATE             = TextAreaField('Label Template', validators=[DataRequired(), IMAGE_LABEL_TEMPLATE_validator])
    IMAGE_EXTRA_TEXT                 = StringField('Extra Image Text File', validators=[IMAGE_EXTRA_TEXT_validator])
    IMAGE_LABEL_SYSTEM               = SelectField('Label Images', choices=IndiAllskyConfigForm.IMAGE_LABEL_SYSTEM_choices, validators=[IMAGE_LABEL_SYSTEM_validator])
    TEXT_PROPERTIES__FONT_FACE       = SelectField('OpenCV Font', choices=IndiAllskyConfigForm.TEXT_PROPERTIES__FONT_FACE_choices, validators=[DataRequired(), TEXT_PROPERTIES__FONT_FACE_validator])
    #TEXT_PROPERTIES__FONT_AA
    TEXT_PROPERTIES__FONT_SCALE      = FloatField('Font Scale', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    TEXT_PROPERTIES__FONT_THICKNESS  = IntegerField('Font Thickness', validators=[DataRequired(), TEXT_PROPERTIES__FONT_THICKNESS_validator])
    TEXT_PROPERTIES__FONT_OUTLINE    = BooleanField('Font Outline')
    TEXT_PROPERTIES__FONT_HEIGHT     = IntegerField('Text Height Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_HEIGHT_validator])
    TEXT_PROPERTIES__FONT_X          = IntegerField('Text X Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_X_validator])
    TEXT_PROPERTIES__FONT_Y          = IntegerField('Text Y Offset', validators=[DataRequired(), TEXT_PROPERTIES__FONT_Y_validator])
    TEXT_PROPERTIES__FONT_COLOR      = StringField('Text Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    TEXT_PROPERTIES__PIL_FONT_FILE   = SelectField('Pillow Font', choices=IndiAllskyConfigForm.TEXT_PROPERTIES__PIL_FONT_FILE_choices, validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_FILE_validator])
    TEXT_PROPERTIES__PIL_FONT_CUSTOM = StringField('Custom Font', validators=[TEXT_PROPERTIES__PIL_FONT_CUSTOM_validator])
    TEXT_PROPERTIES__PIL_FONT_SIZE   = IntegerField('Font Size', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    IMAGE_CIRCLE_MASK__ENABLE        = BooleanField('Enable Image Circle Mask')
    IMAGE_CIRCLE_MASK__DIAMETER      = IntegerField('Mask Diameter', validators=[DataRequired(), IMAGE_CIRCLE_MASK__DIAMETER_validator])
    IMAGE_CIRCLE_MASK__OFFSET_X      = IntegerField('Mask X Offset', validators=[IMAGE_CIRCLE_MASK__OFFSET_X_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    IMAGE_CIRCLE_MASK__OFFSET_Y      = IntegerField('Mask Y Offset', validators=[IMAGE_CIRCLE_MASK__OFFSET_Y_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    IMAGE_CIRCLE_MASK__BLUR          = IntegerField('Mask Blur', validators=[IMAGE_CIRCLE_MASK__BLUR_validator])
    IMAGE_CIRCLE_MASK__OPACITY       = IntegerField('Mask Opacity %', validators=[IMAGE_CIRCLE_MASK__OPACITY_validator])
    IMAGE_CIRCLE_MASK__OUTLINE       = BooleanField('Mask Outline')
    IMAGE_CROP_IMAGE_CIRCLE          = BooleanField('Crop to Image Circle')
    MOON_OVERLAY__ENABLE             = BooleanField('Enable Moon Overlay')
    MOON_OVERLAY__X                  = IntegerField('X', validators=[MOON_OVERLAY__X_validator])
    MOON_OVERLAY__Y                  = IntegerField('Y', validators=[MOON_OVERLAY__Y_validator])
    MOON_OVERLAY__SCALE              = FloatField('Overlay Scale', validators=[DataRequired(), MOON_OVERLAY__SCALE_validator])
    MOON_OVERLAY__DARK_SIDE_SCALE    = FloatField('Dark Side Brightness', validators=[MOON_OVERLAY__DARK_SIDE_SCALE_validator])
    MOON_OVERLAY__FLIP_V             = BooleanField('Flip Vertically')
    MOON_OVERLAY__FLIP_H             = BooleanField('Flip Horizontally')
    LIGHTGRAPH_OVERLAY__ENABLE       = BooleanField('Enable Lightgraph Overlay')
    LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT = IntegerField('Lightgraph Height', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT_validator])
    LIGHTGRAPH_OVERLAY__GRAPH_BORDER = IntegerField('Lightgraph Border', validators=[LIGHTGRAPH_OVERLAY__GRAPH_BORDER_validator])
    LIGHTGRAPH_OVERLAY__Y            = IntegerField('Y', validators=[LIGHTGRAPH_OVERLAY__Y_validator])
    LIGHTGRAPH_OVERLAY__OFFSET_X     = IntegerField('X Offset', validators=[LIGHTGRAPH_OVERLAY__OFFSET_X_validator])
    LIGHTGRAPH_OVERLAY__SCALE        = FloatField('Scale', validators=[LIGHTGRAPH_OVERLAY__SCALE_validator])
    LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE = IntegerField('Time Marker Size', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE_validator])
    LIGHTGRAPH_OVERLAY__DAY_COLOR    = StringField('Day Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__DUSK_COLOR   = StringField('Dusk/Dawn Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__NIGHT_COLOR  = StringField('Night Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__MOONMODE_COLOR = StringField('Moon Mode Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__HOUR_COLOR   = StringField('Hour Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__BORDER_COLOR = StringField('Border Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__NOW_COLOR    = StringField('Time Marker Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__FONT_COLOR   = StringField('Font Color', validators=[DataRequired(), LIGHTGRAPH_OVERLAY__RGB_COLOR_validator])
    LIGHTGRAPH_OVERLAY__OPACITY      = IntegerField('Opacity ', validators=[LIGHTGRAPH_OVERLAY__OPACITY_validator])
    LIGHTGRAPH_OVERLAY__PIL_FONT_SIZE = IntegerField('Font Size (Pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    LIGHTGRAPH_OVERLAY__OPENCV_FONT_SCALE = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    LIGHTGRAPH_OVERLAY__LABEL        = BooleanField('Lightgraph Label')
    LIGHTGRAPH_OVERLAY__HOUR_LINES   = BooleanField('Lightgraph Hour Lines')
    CARDINAL_DIRS__ENABLE            = BooleanField('Enable Cardinal Directions')
    CARDINAL_DIRS__FONT_COLOR        = StringField('Text Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])
    CARDINAL_DIRS__SWAP_NS           = BooleanField('Swap North/South')
    CARDINAL_DIRS__SWAP_EW           = BooleanField('Swap East/West')
    CARDINAL_DIRS__CHAR_NORTH        = StringField('North Character', validators=[CARDINAL_DIRS__CHAR_validator])
    CARDINAL_DIRS__CHAR_EAST         = StringField('East Character', validators=[CARDINAL_DIRS__CHAR_validator])
    CARDINAL_DIRS__CHAR_WEST         = StringField('West Character', validators=[CARDINAL_DIRS__CHAR_validator])
    CARDINAL_DIRS__CHAR_SOUTH        = StringField('South Character', validators=[CARDINAL_DIRS__CHAR_validator])
    CARDINAL_DIRS__DIAMETER          = IntegerField('Image Circle Diameter', validators=[CARDINAL_DIRS__DIAMETER_validator])
    CARDINAL_DIRS__OFFSET_X          = IntegerField('X Offset', validators=[CARDINAL_DIRS__CENTER_OFFSET_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    CARDINAL_DIRS__OFFSET_Y          = IntegerField('Y Offset', validators=[CARDINAL_DIRS__CENTER_OFFSET_validator], render_kw={'readonly' : True, 'disabled' : 'disabled'})
    CARDINAL_DIRS__OFFSET_TOP        = IntegerField('Top Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    CARDINAL_DIRS__OFFSET_LEFT       = IntegerField('Left Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    CARDINAL_DIRS__OFFSET_RIGHT      = IntegerField('Right Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    CARDINAL_DIRS__OFFSET_BOTTOM     = IntegerField('Bottom Offset', validators=[CARDINAL_DIRS__SIDE_OFFSET_validator])
    CARDINAL_DIRS__OPENCV_FONT_SCALE = FloatField('Font Scale (opencv)', validators=[DataRequired(), TEXT_PROPERTIES__FONT_SCALE_validator])
    CARDINAL_DIRS__PIL_FONT_SIZE     = IntegerField('Font Size (pillow)', validators=[DataRequired(), TEXT_PROPERTIES__PIL_FONT_SIZE_validator])
    CARDINAL_DIRS__OUTLINE_CIRCLE    = BooleanField('Image Circle Outline')
    IMAGE_BORDER__TOP                = IntegerField('Image Border Top', validators=[IMAGE_BORDER_SIDE_validator])
    IMAGE_BORDER__LEFT               = IntegerField('Image Border Left', validators=[IMAGE_BORDER_SIDE_validator])
    IMAGE_BORDER__RIGHT              = IntegerField('Image Border Right', validators=[IMAGE_BORDER_SIDE_validator])
    IMAGE_BORDER__BOTTOM             = IntegerField('Image Border Bottom', validators=[IMAGE_BORDER_SIDE_validator])
    IMAGE_BORDER__COLOR              = StringField('Border Color (r,g,b)', validators=[DataRequired(), RGB_COLOR_validator])


class IndiAllskyMiniTimelapseForm(FlaskForm):
    SECONDS_choices = (
        ('60', '1 minute'),
        ('120', '2 minutes'),
        ('180', '3 minutes'),
        ('240', '4 minutes'),
        ('300', '5 minutes'),
        ('360', '6 minutes'),
        ('420', '7 minutes'),
        ('480', '8 minutes'),
        ('540', '9 minutes'),
        ('600', '10 minutes'),
        ('900', '15 minutes'),
        ('1200', '20 minutes'),
        ('1800', '30 minutes'),
        ('2700', '45 minutes'),
        ('3600', '1 hour'),
        ('5400', '1.5 hours'),
        ('7200', '2 hours'),
        ('7200', '2 hours'),
        ('10800', '3 hours'),
        ('14400', '4 hours'),
        ('21600', '6 hours'),
        ('28800', '8 hours'),
        ('43200', '12 hours'),
    )

    FRAMERATE_SELECT_choices = (
        ('0.25', '0.25 FPS'),
        ('0.5', '0.5 FPS'),
        ('0.75', '0.75 FPS'),
        ('1', '1 FPS'),
        ('2', '2 FPS'),
        ('5', '5 FPS'),
        ('10', '10 FPS'),
        ('25', '25 FPS'),
        ('30', '30 FPS'),
        ('60', '60 FPS'),
    )

    BITRATE_SELECT_choices = {
        'Compact files': (
            ('2500k', '2.5 Mbps — about 19 MB/min'),
            ('5000k', '5 Mbps — about 38 MB/min'),
        ),
        'Medium files': (
            ('10000k', '10 Mbps — about 75 MB/min'),
            ('15000k', '15 Mbps — about 113 MB/min'),
        ),
        'Large files': (
            ('20000k', '20 Mbps — about 150 MB/min'),
            ('30000k', '30 Mbps — about 225 MB/min'),
        ),
        'Very large files': (
            ('40000k', '40 Mbps — about 300 MB/min'),
            ('50000k', '50 Mbps — about 375 MB/min'),
        ),
    }

    CAMERA_ID                        = HiddenField('Camera ID', validators=[DataRequired()])
    IMAGE_ID                         = HiddenField('Image ID', validators=[DataRequired()])
    PRE_SECONDS_SELECT               = SelectField('Before selected image', choices=SECONDS_choices, validators=[DataRequired()])
    POST_SECONDS_SELECT              = SelectField('After selected image', choices=SECONDS_choices, validators=[DataRequired()])
    FRAMERATE_SELECT                 = SelectField('Speed', choices=FRAMERATE_SELECT_choices, validators=[DataRequired()])
    BITRATE_SELECT                   = SelectField('Bitrate/File size', choices=BITRATE_SELECT_choices, validators=[DataRequired()])
    NOTE                             = StringField('Description', validators=[DataRequired()])


class IndiAllskyLongTermKeogramForm(FlaskForm):
    END_SELECT_choices = (
        ('today', 'Today'),
        ('thisyear', 'End of this year'),
        ('lastyear', 'End of last year'),
    )

    DAYS_SELECT_choices = (
        ('30', '1 Month'),
        ('90', '3 Months'),
        ('180', '6 Months'),
        ('365', '1 Year'),
        ('730', '2 Years'),
        ('1095', '3 Years'),
        ('42', 'All Available'),  # special
    )

    PIXELS_SELECT_choices = (
        ('1', '1'),
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
        ('5', '5'),
    )

    ALIGNMENT_SELECT_choices = (
        ('20', '20 Seconds'),
        ('30', '30 Seconds'),
        ('40', '40 Seconds'),
        ('50', '50 Seconds'),
        ('60', '60 Seconds'),
        ('75', '75 Seconds'),
        ('90', '90 Seconds'),
        ('120', '120 Seconds'),
    )

    OFFSET_SELECT_choices = (
        ('-43200', '-12'),
        ('-39600', '-11'),
        ('-36000', '-10'),
        ('-32400', '-9'),
        ('-28800', '-8'),
        ('-25200', '-7'),
        ('-21600', '-6'),
        ('-18000', '-5'),
        ('-14400', '-4'),
        ('-10800', '-3'),
        ('-7200', '-2'),
        ('-3600', '-1'),
        ('0', '0'),
        ('3600', '1'),
        ('7200', '2'),
        ('10800', '3'),
        ('14400', '4'),
        ('18000', '5'),
        ('21600', '6'),
        ('25200', '7'),
        ('28800', '8'),
        ('32400', '9'),
        ('36000', '10'),
        ('39600', '11'),
        ('43200', '12'),
    )

    CAMERA_ID               = HiddenField('Camera ID', validators=[DataRequired()])
    END_SELECT              = SelectField('Start', choices=END_SELECT_choices, default=END_SELECT_choices[0][0], validators=[DataRequired()])
    DAYS_SELECT             = SelectField('Timeframe', choices=DAYS_SELECT_choices, default=DAYS_SELECT_choices[0][0], validators=[DataRequired()])
    PIXELS_SELECT           = SelectField('Pixels per Day', choices=PIXELS_SELECT_choices, default=PIXELS_SELECT_choices[4][0], validators=[DataRequired()])
    ALIGNMENT_SELECT        = SelectField('Alignment', choices=ALIGNMENT_SELECT_choices, default=ALIGNMENT_SELECT_choices[4][0], validators=[DataRequired()])
    OFFSET_SELECT           = SelectField('Hour Offset', choices=OFFSET_SELECT_choices, default=OFFSET_SELECT_choices[12][0], validators=[DataRequired()])
    REVERSE                 = BooleanField('Reverse')
    LABEL                   = BooleanField('Label')


class IndiAllskyNetworkManagerForm(FlaskForm):
    HOTSPOT_BAND_choices = (
        ('bg', '802.11b/g [2.4Ghz]'),
        ('a', '802.11a [5Ghz]'),
    )


    CONNECTIONS_SELECT         = SelectField('Connection', choices=[], validators=[])
    WIFI_DEVICES_SELECT        = SelectField('Wi-Fi Devices', choices=[], validators=[])
    SSID_SELECT                = SelectField('SSID', choices=[], validators=[])
    SSID_PSK                   = PasswordField('PSK', widget=PasswordInput(hide_value=False), validators=[], render_kw={'autocomplete' : 'new-password'})
    SSID_PRIORITY              = IntegerField('Priority', default=0, validators=[], widget=NumberInput(step=10))
    SSID_RETRIES               = IntegerField('Auto-Connect Retries', default=4, validators=[])
    HOTSPOT_DEVICES_SELECT     = SelectField('Wi-Fi Devices', choices=[], validators=[])
    HOTSPOT_SSID               = StringField('Hotspot SSID', default='indi-allsky Hotspot', validators=[])
    HOTSPOT_BAND               = SelectField('Hotspot Band', choices=HOTSPOT_BAND_choices, validators=[])
    HOTSPOT_PSK                = PasswordField('Hotspot PSK', widget=PasswordInput(hide_value=False), validators=[], render_kw={'autocomplete' : 'new-password'})
    HOTSPOT_NOSECURITY         = BooleanField('No Security')


    nm_conn_states_str = {
        0 : 'Unknown',
        1 : 'Activating',
        2 : 'Active',
        3 : 'Deactivating',
        4 : 'Not Active',
    }


    nm_device_types = {
        '802-3-ethernet' : 1,
        '802-11-wireless': 2,
    }

    nm_powersave_str = {
        0 : 'Default (Enabled)',
        1 : 'Ignore',
        2 : 'Disabled',
        3 : 'Enabled',
    }


    def __init__(self, *args, **kwargs):
        super(IndiAllskyNetworkManagerForm, self).__init__(*args, **kwargs)

        self.CONNECTIONS_SELECT.choices = self.getConnections()

        wifi_devices = self.getWifiDevices()
        self.WIFI_DEVICES_SELECT.choices = wifi_devices
        self.HOTSPOT_DEVICES_SELECT.choices = wifi_devices


    def getConnections(self):
        try:
            bus = dbus.SystemBus()
        except dbus.exceptions.DBusException:
            return (['D-Bus Unavailable', 'D-Bus Unavailable'],)


        try:
            nm_settings = bus.get_object("org.freedesktop.NetworkManager",
                                         "/org/freedesktop/NetworkManager/Settings")
        except dbus.exceptions.DBusException as e:
            app.logger.error('D-Bus Exception: %s', str(e))
            return [(
                'error', 'D-Bus Exception: {0:s}'.format(str(e))
            )]


        settingspath_list = nm_settings.Get("org.freedesktop.NetworkManager.Settings",
                                            "Connections",
                                            dbus_interface=dbus.PROPERTIES_IFACE)


        conn_dict = dict()
        for settings_path in settingspath_list:
            settings = bus.get_object("org.freedesktop.NetworkManager",
                                      settings_path)


            settings_connection = dbus.Interface(settings,
                                                 "org.freedesktop.NetworkManager.Settings.Connection")

            settings_dict = settings_connection.GetSettings()

            settings_uuid = str(settings_dict['connection']['uuid'])
            #app.logger.info('Uuid: %s', settings_uuid)

            #app.logger.info('Settings: %s', settings_dict)
            #app.logger.info('Keys: %s', settings_dict['connection'].keys())


            conn_dict[settings_uuid] = {
                'id' : str(settings_dict['connection']['id']),
                'interface' : str(settings_dict['connection'].get('interface-name', '')),
                'devices' : [str(settings_dict['connection'].get('interface-name', ''))],  # override later
                'active' : False,  # override later
                'state' : 'Down',  # override later
                'autoconnect' : bool(settings_dict['connection'].get('autoconnect', True)),
                'autoconnect-priority' : int(settings_dict['connection'].get('autoconnect-priority', 0)),
            }


            # look for static addresses
            pre_conn_address_list = settings_dict.get('ipv4', {}).get('address-data', [])  # ipv4 may be empty

            pre_address_list = list()
            for address in pre_conn_address_list:
                address_str = '{0:s}'.format(str(address['address']))
                pre_address_list.append(address_str)


            # These will be will be overwritten if the interface is active
            if pre_address_list:
                conn_dict[settings_uuid]['addresses'] = pre_address_list
            else:
                conn_dict[settings_uuid]['addresses'] = ['No address']



            settings_type = str(settings_dict['connection']['type'])
            if settings_type == '802-3-ethernet':
                conn_dict[settings_uuid]['type'] = '802-3-ethernet'
            elif settings_type == '802-11-wireless':
                conn_dict[settings_uuid]['type'] = '802-11-wireless'
                conn_dict[settings_uuid]['powersave'] = int(settings_dict['802-11-wireless'].get('powersave', -1))
            else:
                conn_dict[settings_uuid]['type'] = 'other'

            #app.logger.info('ID: %s, Uuid: %s, Type: %s, Interface: %s', settings_id, settings_uuid, settings_type, settings_int)


        nm = bus.get_object("org.freedesktop.NetworkManager",
                            "/org/freedesktop/NetworkManager")

        # get active connections
        connpath_list = nm.Get("org.freedesktop.NetworkManager",
                               "ActiveConnections",
                               dbus_interface=dbus.PROPERTIES_IFACE)


        for conn_path in connpath_list:
            conn = bus.get_object("org.freedesktop.NetworkManager",
                                  conn_path)


            #conn_type = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
            #                     "Type",
            #                     dbus_interface=dbus.PROPERTIES_IFACE)


            #conn_id = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
            #                   "Id",
            #                   dbus_interface=dbus.PROPERTIES_IFACE)

            conn_uuid = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
                                 "Uuid",
                                 dbus_interface=dbus.PROPERTIES_IFACE)


            conn_state_enum = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
                                       "State",
                                       dbus_interface=dbus.PROPERTIES_IFACE)

            try:
                conn_state = self.nm_conn_states_str[int(conn_state_enum)]
            except KeyError:
                conn_state = 'UNDEFINED'


            ipv4config_path = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
                                       "Ip4Config",
                                       dbus_interface=dbus.PROPERTIES_IFACE)

            ipv4config = bus.get_object(
                "org.freedesktop.NetworkManager",
                ipv4config_path)


            conn_address_list = list()
            try:
                address_data = ipv4config.Get("org.freedesktop.NetworkManager.IP4Config",
                                              "AddressData",
                                              dbus_interface=dbus.PROPERTIES_IFACE)

                for address in address_data:
                    #address_str = '{0:s}/{1:d}'.format(address['address'], address['prefix'])
                    address_str = '{0:s}'.format(str(address['address']))
                    conn_address_list.append(address_str)
            except dbus.exceptions.DBusException as e:
                app.logger.error('D-Bus Exception: %s', str(e))


            devicespath_list = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
                                        "Devices",
                                        dbus_interface=dbus.PROPERTIES_IFACE)


            conn_device_list = list()
            for device_path in devicespath_list:
                device_config = bus.get_object("org.freedesktop.NetworkManager",
                                               device_path)

                device_int = device_config.Get("org.freedesktop.NetworkManager.Device",
                                               "Interface",
                                               dbus_interface=dbus.PROPERTIES_IFACE)

                conn_device_list.append(str(device_int))


            conn_dict[conn_uuid]['active'] = True
            conn_dict[conn_uuid]['devices'] = conn_device_list
            conn_dict[conn_uuid]['addresses'] = conn_address_list
            conn_dict[conn_uuid]['state'] = conn_state



        conn_select_wifi_list = list()
        conn_select_ethernet_list = list()
        conn_select_other_list = list()


        # sort based on priority
        conn_items_list_sorted = sorted(conn_dict.items(), key=lambda x: x[1]['autoconnect-priority'], reverse=True)


        for c in filter(lambda item: item[1]['type'] == '802-11-wireless', conn_items_list_sorted):
            try:
                powersave_str = self.nm_powersave_str[c[1]['powersave']]
            except KeyError:
                powersave_str = 'UNKNOWN'

            autostart_str = '*' if c[1]['autoconnect'] else ''

            conn_select_wifi_list.append((
                c[0],
                '{0:s}{1:s} [{2:s}] - {3:s} - {4:s} [prio: {5:d}] [powersave: {6:s}]'.format(
                    autostart_str,
                    c[1]['id'],
                    ','.join(c[1]['devices']),
                    ','.join(c[1]['addresses']),
                    c[1]['state'],
                    c[1]['autoconnect-priority'],
                    powersave_str,
                )
            ))

        for c in filter(lambda item: item[1]['type'] == '802-3-ethernet', conn_items_list_sorted):
            autostart_str = '*'if c[1]['autoconnect'] else ''
            conn_select_ethernet_list.append((
                c[0],
                '{0:s}{1:s} [{2:s}] - {3:s} - {4:s} [prio: {5:d}]'.format(
                    autostart_str,
                    c[1]['id'],
                    ','.join(c[1]['devices']),
                    ','.join(c[1]['addresses']),
                    c[1]['state'],
                    c[1]['autoconnect-priority'],
                )
            ))

        for c in filter(lambda item: item[1]['type'] == 'other', conn_items_list_sorted):
            autostart_str = '*'if c[1]['autoconnect'] else ''
            conn_select_other_list.append((
                c[0],
                '{0:s}{1:s} [{2:s}] - {3:s} - {4:s}'.format(
                    autostart_str,
                    c[1]['id'],
                    ','.join(c[1]['devices']),
                    ','.join(c[1]['addresses']),
                    c[1]['state'],
                )
            ))


        # setting some defaults
        conn_select_choices = {
            'Wi-Fi' : [('', '--- No managed wifi connections ---')],
            'Ethernet' : [('', '--- No managed ethernet connections ---')],
        }


        if conn_select_wifi_list:
            conn_select_choices['Wi-Fi'] = conn_select_wifi_list


        if conn_select_ethernet_list:
            conn_select_choices['Ethernet'] = conn_select_ethernet_list


        if conn_select_other_list:
            conn_select_choices['Other'] = conn_select_other_list


        #app.logger.info('%s', conn_select_choices)
        return conn_select_choices


    def getWifiDevices(self):
        try:
            bus = dbus.SystemBus()
        except dbus.exceptions.DBusException:
            return (['D-Bus Unavailable', 'D-Bus Unavailable'],)


        try:
            nm = bus.get_object("org.freedesktop.NetworkManager",
                                "/org/freedesktop/NetworkManager")
        except dbus.exceptions.DBusException as e:
            app.logger.error('D-Bus Exception: %s', str(e))
            return [(
                'error', 'D-Bus Exception: {0:s}'.format(str(e))
            )]


        # get active connections
        devpath_list = nm.Get("org.freedesktop.NetworkManager",
                              "AllDevices",
                              dbus_interface=dbus.PROPERTIES_IFACE)

        wifi_dev_select_list = list()
        for dev_path in devpath_list:
            dev = bus.get_object("org.freedesktop.NetworkManager",
                                 dev_path)


            device_type = dev.Get("org.freedesktop.NetworkManager.Device",
                                  "DeviceType",
                                  dbus_interface=dbus.PROPERTIES_IFACE)
            #app.logger.info('Device Type: %s', device_type)


            if int(device_type) != self.nm_device_types['802-11-wireless']:
                continue


            device_int = dev.Get("org.freedesktop.NetworkManager.Device",
                                 "Interface",
                                 dbus_interface=dbus.PROPERTIES_IFACE)


            conn_path = dev.Get("org.freedesktop.NetworkManager.Device",
                                "ActiveConnection",
                                dbus_interface=dbus.PROPERTIES_IFACE)


            if conn_path == '/':
                # this usually means a connection is inactive or not defined
                desc = '{0:s} [Not Active]'.format(str(device_int))
            else:
                conn = bus.get_object("org.freedesktop.NetworkManager",
                                      conn_path)


                conn_id = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
                                   "Id",
                                   dbus_interface=dbus.PROPERTIES_IFACE)

                desc = '{0:s} [{1:s}]'.format(str(device_int), str(conn_id))


            wifi_dev_select_list.append((
                str(device_int), desc
            ))


        if not wifi_dev_select_list:
            return [(
                '', '--- No wifi devices available ---'
            )]

        #app.logger.info('%s', wifi_dev_select_list)
        return wifi_dev_select_list


class IndiAllskyDriveManagerForm(FlaskForm):

    DRIVES_SELECT         = SelectField('Drive', choices=[], validators=[])
    DEVICES_SELECT        = SelectField('Mount', choices=[], validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyDriveManagerForm, self).__init__(*args, **kwargs)

        self.DRIVES_SELECT.choices = self.getDrives()
        self.DEVICES_SELECT.choices = self.getDevices()


    def getDrives(self, removable=False):
        try:
            bus = dbus.SystemBus()
        except dbus.exceptions.DBusException:
            return (['D-Bus Unavailable', 'D-Bus Unavailable'],)


        try:
            nm_udisks2 = bus.get_object(
                "org.freedesktop.UDisks2",
                "/org/freedesktop/UDisks2")
        except dbus.exceptions.DBusException as e:
            app.logger.error('D-Bus Exception: %s', str(e))
            return [(
                '', 'D-Bus Exception: {0:s}'.format(str(e))
            )]

        iface = dbus.Interface(
            nm_udisks2,
            'org.freedesktop.DBus.ObjectManager')


        object_paths = iface.GetManagedObjects()

        drive_list = list()
        for object_path in object_paths:
            if not object_path.startswith('/org/freedesktop/UDisks2/drives/'):
                continue

            settings = bus.get_object(
                "org.freedesktop.UDisks2",
                object_path)

            settings_connection = dbus.Interface(
                settings,
                dbus_interface='org.freedesktop.DBus.Properties')

            settings_dict = settings_connection.GetAll('org.freedesktop.UDisks2.Drive')


            drive_Removable = int(settings_dict['Removable'])
            drive_CanPowerOff = int(settings_dict['CanPowerOff'])
            if removable:
                if not drive_CanPowerOff:
                    continue


            drive_Vendor = str(settings_dict['Vendor'])
            if not drive_Vendor:
                drive_Vendor = '[No Vendor]'


            drive_ConnectionBus = str(settings_dict['ConnectionBus'])
            if not drive_ConnectionBus:
                drive_ConnectionBus = '[Internal]'


            drive_dict = {
                'Id' : str(settings_dict['Id']),
                'Vendor' : drive_Vendor,
                'Model' : str(settings_dict['Model']),
                'Size' : int(settings_dict['Size']),
                'ConnectionBus' : drive_ConnectionBus,
                'Removable' : drive_Removable,
                'CanPowerOff' : drive_CanPowerOff,
            }


            drive_list.append(drive_dict)


        drive_list_sorted = sorted(drive_list, key=lambda x: x['CanPowerOff'], reverse=True)


        drive_entries = list()
        for drive in drive_list_sorted:
            desc = '{0:s} - {1:s} - {2:0.1f} GB - {3:s}'.format(drive['Vendor'], drive['Model'], float(drive['Size']) / 1024 / 1024 / 1024, drive['ConnectionBus'])

            drive_entries.append((drive['Id'], desc))


        if not drive_entries:
            drive_entries.append(('', 'No Removable Drives'))

        return drive_entries


    def getDevices(self, mounted=True):
        try:
            bus = dbus.SystemBus()
        except dbus.exceptions.DBusException:
            return (['D-Bus Unavailable', 'D-Bus Unavailable'],)


        try:
            nm_udisks2 = bus.get_object(
                "org.freedesktop.UDisks2",
                "/org/freedesktop/UDisks2")
        except dbus.exceptions.DBusException as e:
            app.logger.error('D-Bus Exception: %s', str(e))
            return [(
                '', 'D-Bus Exception: {0:s}'.format(str(e))
            )]

        iface = dbus.Interface(
            nm_udisks2,
            'org.freedesktop.DBus.ObjectManager')


        objects = iface.GetManagedObjects()

        device_list = list()
        for object_path, object_info in objects.items():
            if not object_path.startswith('/org/freedesktop/UDisks2/block_devices/'):
                continue


            if 'org.freedesktop.UDisks2.Filesystem' not in object_info:
                continue


            settings = bus.get_object(
                "org.freedesktop.UDisks2",
                object_path)

            settings_connection = dbus.Interface(
                settings,
                dbus_interface='org.freedesktop.DBus.Properties')

            settings_dict = settings_connection.GetAll('org.freedesktop.UDisks2.Block')

            #for k in object_info.keys():
            #    app.logger.info('Key: %s', k)

            #app.logger.info('Info: %s', object_info)
            device_dict = {
                'Id' : str(settings_dict['Id']),
                'Device' : "".join(chr(i) for i in settings_dict['Device'][:-1]),  # trim null char
                'Drive' : str(object_info['org.freedesktop.UDisks2.Block']['Drive']),
                # if the drive is abstracted or not defined "Drive" will be '/'
            }


            if len(object_info['org.freedesktop.UDisks2.Filesystem']['MountPoints']) > 0:
                device_dict['MountPoints0'] = "".join(chr(i) for i in object_info['org.freedesktop.UDisks2.Filesystem']['MountPoints'][0][:-1])  # trim null char
            else:
                device_dict['MountPoints0'] = 'UNMOUNTED'


            if device_dict['Drive'] != '/':
                # lookup the drive
                drive_objects = iface.GetManagedObjects()

                for drive_object_path in drive_objects:
                    if not drive_object_path.startswith('/org/freedesktop/UDisks2/drives/'):
                        continue

                    if drive_object_path != device_dict['Drive']:
                        continue

                    drive_settings = bus.get_object(
                        "org.freedesktop.UDisks2",
                        drive_object_path)

                    drive_settings_connection = dbus.Interface(
                        drive_settings,
                        dbus_interface='org.freedesktop.DBus.Properties')


                    drive_settings_dict = drive_settings_connection.GetAll('org.freedesktop.UDisks2.Drive')

                    device_dict['Drive_Id'] = str(drive_settings_dict['Id'])

                    break
                else:
                    # this should not happen
                    device_dict['Drive_Id'] = 'Drive not found'
            else:
                device_dict['Drive_Id'] = ''


            device_list.append(device_dict)


        device_list_sorted = sorted(device_list, key=lambda x: x['Drive'], reverse=True)

        device_entries = list()
        for device in device_list_sorted:
            desc = '{0:s} - [{1:s}] - {2:s}'.format(device['MountPoints0'], device['Device'], device['Drive_Id'])

            device_entries.append((device['Id'], desc))


        if not device_entries:
            device_entries.append(('', 'No Devices'))

        return device_entries


class IndiAllskyIndiServerChangeForm(FlaskForm):
    CAMERA_SERVER_SELECT    = SelectField('Available Camera Drivers', choices=[], validators=[])
    GPS_SERVER_SELECT       = SelectField('Available GPS Drivers', choices=[], validators=[])
    RESTART_INDISERVER      = BooleanField('Restart indiserver')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyIndiServerChangeForm, self).__init__(*args, **kwargs)

        self.CAMERA_SERVER_SELECT.choices = self.getCameraServers()
        self.GPS_SERVER_SELECT.choices = self.getGpsServers()


    def getCameraServers(self):
        select_list = [
            ['', 'None'],
        ]


        if Path('/usr/local/bin/indiserver').exists():
            indiserver_p = Path('/usr/local/bin/indiserver')
        elif Path('/usr/bin/indiserver').exists():
            indiserver_p = Path('/usr/bin/indiserver')
        else:
            return select_list


        for server in constants.INDISERVER_CAMERA_MAP.keys():
            if indiserver_p.parent.joinpath(server).exists():
                select_list.append([server, '{0:s} - [{1:s}]'.format(constants.INDISERVER_CAMERA_MAP[server], server)])


        return select_list


    def getGpsServers(self):
        select_list = [
            ['', 'None'],
        ]


        if Path('/usr/local/bin/indiserver').exists():
            indiserver_p = Path('/usr/local/bin/indiserver')
        elif Path('/usr/bin/indiserver').exists():
            indiserver_p = Path('/usr/bin/indiserver')
        else:
            return select_list


        for server in constants.INDISERVER_GPS_MAP.keys():
            if indiserver_p.parent.joinpath(server).exists():
                select_list.append([server, '{0:s} - [{1:s}]'.format(constants.INDISERVER_GPS_MAP[server], server)])


        return select_list


class IndiAllskyImageCircleHelperForm(FlaskForm):
    LINE_COLOR_choices = (
        ('#00ff00', 'Green'),
        ('#ff0000', 'Red'),
        ('#0000ff', 'Blue'),
        ('#ff00ff', 'Magenta'),
        ('#ffff00', 'Yellow'),
        ('#00ffff', 'Cyan'),
        ('#202020', 'Darker Gray'),
        ('#303030', 'Dark Gray'),
        ('#808080', 'Gray'),
        ('#ffffff', 'White'),
    )


    IMAGE_CIRCLE_DIAMETER   = IntegerField('Diameter', widget=NumberInput(step=5))
    OFFSET_X                = IntegerField('X Offset', default=0, widget=NumberInput(step=10))
    OFFSET_Y                = IntegerField('Y Offset', default=0, widget=NumberInput(step=10))
    LINE_WIDTH              = IntegerField('Line Width', default=5)
    LINE_COLOR              = SelectField('Line Color', choices=LINE_COLOR_choices)
    KEOGRAM_LINE            = BooleanField('Keogram Line')
    KEOGRAM_ANGLE           = FloatField('Keogram Angle', widget=NumberInput(min=-180, max=180, step=0.1))
    AZIMUTH_ANGLE           = FloatField('Azimuth Angle', widget=NumberInput(min=0, max=359.9, step=0.1))


class IndiAllskyVirtualSkyHelperForm(FlaskForm):
    AZIMUTH_ANGLE           = FloatField('Azimuth Angle', widget=NumberInput(min=0.0, max=359.9, step=0.1))
    LATITUDE_OFFSET         = FloatField('Latitude Offset', widget=NumberInput(step=0.25))
    LONGITUDE_OFFSET        = FloatField('Longitude Offset', widget=NumberInput(step=0.25))
    IMAGE_CIRCLE_DIAMETER   = IntegerField('Diameter', widget=NumberInput(step=5))
    OFFSET_X                = IntegerField('X Offset', default=0, widget=NumberInput(step=10))
    OFFSET_Y                = IntegerField('Y Offset', default=0, widget=NumberInput(step=10))
    MAGNITUDE               = FloatField('Magnitude', widget=NumberInput(step=0.25))
    CONSTELLATIONS          = BooleanField('Constellations')
    CONSTELLATIONLABELS     = BooleanField('Label')
    SHOWSTARS               = BooleanField('Stars')
    SHOWSTARLABELS          = BooleanField('Label')
    SHOWPLANETS             = BooleanField('Planets')
    SHOWPLANETLABELS        = BooleanField('Label')


class IndiAllskyCameraSimulatorForm(FlaskForm):
    SENSOR_SELECT_choices = {
        'Small' : (
            ('imx219', 'IMX219 - 1/4" - Camera Module 2'),
            ('imx415_sv205', 'SV205C - 1/2.8" (IMX415)'),
            ('ov5647', 'OV5647 - 1/4" - Camera Module 1'),
        ),
        'Medium - 6mm Class' : (
            ('ar0130', 'ASI120 - 1/3" - AR0130CS'),
            ('imx224', 'IMX224 - 1/3"'),
            ('imx225', 'IMX225 - 1/3"'),
            ('imx273', 'IMX273 - 1/2.9"'),
            ('imx287', 'IMX287 - 1/2.9"'),
            ('imx290', 'IMX290 - 1/2.8"'),
            ('imx296', 'IMX296 - 1/2.9" - Global Shutter'),
            ('imx298', 'IMX298 - 1/2.8"'),
            ('imx307', 'IMX307 - 1/2.8" - SV105C'),
            ('imx327', 'IMX327 - 1/2.8"'),
            ('imx415', 'IMX415 - 1/2.8"'),
            ('imx462', 'IMX462 - 1/2.8"'),
            ('imx662', 'IMX662 - 1/2.8"'),
            ('imx715', 'IMX715 - 1/2.8"'),
            ('mt9m034', 'QHY5LII - 1/3" - MT9M034'),
        ),
        'Medium - 7mm Class' : (
            ('ar0234', 'AR0234 - 1/2.6" - Global Shutter'),
            ('imx230', 'IMX230 - 1/2.4"'),
            ('imx519', 'IMX519 - 1/2.53"'),
            ('imx708', 'IMX708 - 1/2.43" - Camera Module 3'),
        ),
        'Medium - 8mm Class' : (
            ('imx185', 'IMX185 - 1/1.9"'),
            ('imx378', 'IMX378 - 1/2.3"'),
            ('imx385', 'IMX385 - 1/1.9"'),
            ('imx477', 'IMX477 - 1/2.3" - HQ Camera'),
            ('icx205al', 'ICX205AL - 1/2" - SX Superstar'),
            ('icx267al', 'ICX267AL - 1/2" - SX Oculus'),
            ('mt9t001', 'MT9T001 - 1/2"'),
        ),
        'Medium - 9mm Class' : (
            ('icx274al', 'ICX274AL - 1/1.8"'),
            ('imx178', 'IMX178 - 1/1.8"'),
            ('imx252', 'IMX252 - 1/1.8"'),
            ('imx265', 'IMX265 - 1/1.8"'),
            ('imx464', 'IMX464 - 1/1.8" - POA Neptune-C II'),
            ('imx664', 'IMX664 - 1/1.8" - POA Neptune 664C'),
            ('imx678', 'IMX678 - 1/1.8"'),
            ('imx682', 'IMX682 - 1/1.7" - 64MP Hawkeye'),
            ('sc2210', 'SC2210 - 1/1.8" - ASI220'),
        ),
        'Medium - 10-13mm Class' : (
            ('ov64a40', 'OV64A40 - 1/1.32 - 64MP OwlSight'),
            ('imx250', 'IMX250 - 2/3"'),
            ('imx264', 'IMX264 - 2/3"'),
            ('imx429', 'IMX429 - 2/3" - POA Apollo-M MINI'),
            ('imx482', 'IMX482 - 1/1.2"'),
            ('imx485', 'IMX485 - 1/1.2"'),
            ('imx585', 'IMX585 - 1/1.2"'),
            ('imx676', 'IMX676 - 1/1.6"'),
            ('icx825al', 'ICX825AL - 2/3" - SX ULTRASTAR PRO'),
        ),
        'Large' : (
            ('imx174', 'IMX174 - 1/1.2"'),
            ('imx183', 'IMX183 - 1"'),
            ('imx249', 'IMX249 - 1/1.2" - POA Xena-M'),
            ('imx253', 'IMX253 - 1.1"'),
            ('imx283', 'IMX283 - 1" - Arducam Klarity'),
            ('imx304', 'IMX304 - 1.1"'),
            ('imx432', 'IMX432 - 1.1"'),
            ('imx533', 'IMX533 - 1"'),
        ),
        'Extra Large' : (
            ('imx269', 'IMX269 - 4/3"'),
            ('imx294', 'IMX294 - 4/3"'),
            ('imx410', 'IMX410 - Full Frame - ASI2400'),
            ('imx455', 'IMX455 - Full Frame - ASI6200'),
            ('imx571', 'IMX571 - APS-C - ASI2600'),
        ),
    }

    LENS_SELECT_choices = {
        'Small' : (
            ('m12_f2.1_0.76mm_1-3.2', 'M12 0.76mm ƒ/2.1 [M12] - 222° - 1/3.2" ∅2.77mm'),
            ('m12_f2.2_1.71mm_1-3', 'M12 1.71mm ƒ/2.2 [M12] - 184° - 1/3" ∅3.5mm'),
            ('m12_f2.0_1.44mm_1-2.5', 'M12 1.44mm ƒ/2.0 [M12] - 180° - 1/2.5" ∅3.55mm'),
        ),
        'Medium' : (
            ('fe185c046ha_f1.4_1.4mm_1-2', 'Fujinon 1.4mm ƒ/1.4 [C/CS] - 185° - 1/2" ∅4.6mm'),
            ('sunex_dsl215_m12_f2.0_1.55mm_1-2', 'Sunex DSL215 1.55mm ƒ/2.0 [M12] - 185° - 1/2" ∅4.7mm'),
            ('arecont_f2.0_1.55mm_1-2', 'Arecont 1.55mm ƒ/2.0 [C/CS] - 180° - 1/2" ∅4.8mm'),
            ('stardot_f1.5_1.55mm_1-2', 'Stardot 1.55mm ƒ/1.5 [C/CS] - 180° - 1/2" ∅4.8mm'),
            ('m12_f2.4_1.8mm_1-4', 'M12 1.8mm ƒ/2.4 [M12] - 125° - 1/4" ∅4.8mm'),
            ('m12_f2.0_1.56mm_1-2.5', 'M12 1.56mm ƒ/2.0 [M12] - 185° - 1/2.5" ∅4.8mm'),
            ('m12_f2.0_1.7mm_1-2.5', 'M12 1.7mm ƒ/2.0 [M12] - 180° - 1/2.5" ∅5.6mm'),
            ('fe185c057ha_f1.4_1.8mm_2-3', 'Fujinon 1.8mm ƒ/1.4 [C/CS] - 185° - 2/3" ∅5.7mm'),
            ('m12_f2.0_1.85mm_1-1.8', 'M12 1.85mm ƒ/2.0 [M12] - 180° - 1/1.8" ∅5.8mm'),
            ('wgwk-3130-a1_m12_f1.8_1.91mm_1-2.3', 'WGWK-3130 M12 1.91mm ƒ/1.8 [M12] - 185° - 1/2.3" ∅6.4mm'),
            ('cs-2.5ir_8mp_-f_f1.6_2.5mm_2-3', 'CS-2.5IR(8MP)-F 2.5mm ƒ/1.6 [C/CS] - 190° - 2/3 ∅6.4mm'),
            ('zwo_f2.0_2.1mm_1-3', 'ZWO 2.1mm ƒ/2.0 [C/CS] - 150° - 1/3" ∅6.7mm'),
            ('zwo_f1.2_2.5mm_1-2', 'ZWO 2.5mm ƒ/1.2 [C/CS] - 170° - 1/2" ∅6.7mm'),
            ('m12_f2.0_2.1mm_1-2.7', 'M12 2.1mm ƒ/2.0 [M12] - 170° - 1/2.7" ∅6.7mm'),
            ('m12_f2.0_1.8mm_1-2.5', 'M12 1.8mm ƒ/2.0 [M12] - 180° - 1/2.5" ∅6.9mm'),
        ),
        'Large' : (
            ('fe185c086ha_f1.8_2.7mm_1', 'Fujinon 2.7mm ƒ/1.8 [C/CS] - 185° - 1" ∅8.6mm'),
            ('vm2.8ir10mp_f1.6_2.8mm_1-1.8', 'VM2.8IR10MP 2.8mm ƒ/1.6 [C/CS] - 190° - 1/1.8" ∅9.0mm'),
            ('meike_f2.8_3.5mm_4-3', 'Meike 3.5mm ƒ/2.8 Fisheye [MFT] - 220° - 4/3" ∅12.5mm'),
            ('7artisans_f2.8_4.0mm_4-3', '7Artisans 4mm ƒ/2.8 Fisheye [Camera] - 225° - 4/3" ∅12.37mm'),
            ('laowa_f2.8_4.0mm_4-3', 'Laowa 4mm ƒ/2.8 Fisheye - [Camera] 210° - 4/3 ∅13.4mm'),
            ('cil505_f2.2_4.9mm', 'CIL505 4.9mm ƒ/2.2 Fisheye [C/CS] - 180° - ∅14.2mm'),
            ('custom_f7_5.8mm_m42', 'Custom 5.8mm ƒ/7 [M42] - 174° - ∅17.3mm'),
        ),
    }

    SENSOR_SELECT     = SelectField('Sensor', choices=SENSOR_SELECT_choices)
    LENS_SELECT       = SelectField('Lens', choices=LENS_SELECT_choices)
    OFFSET_X          = IntegerField('X Offset', default=0, widget=NumberInput(step=25))
    OFFSET_Y          = IntegerField('Y Offset', default=0, widget=NumberInput(step=25))


