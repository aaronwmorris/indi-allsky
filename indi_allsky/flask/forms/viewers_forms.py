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

class IndiAllskyImageViewer(FlaskForm):
    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    DAY_SELECT           = SelectField('Day', choices=[], validators=[])
    HOUR_SELECT          = SelectField('Hour', choices=[], validators=[])
    IMG_SELECT           = SelectField('Image', choices=[], validators=[])
    FILTER_DETECTIONS    = BooleanField('Detections')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyImageViewer, self).__init__(*args, **kwargs)

        self.detections_count = kwargs.get('detections_count', 0)
        self.s3_prefix = kwargs.get('s3_prefix', '')
        self.camera_id = kwargs.get('camera_id')
        self.local = kwargs.get('local')
        self.asi676mc_diagnostic_download_enabled = kwargs.get(
            'asi676mc_diagnostic_download_enabled',
            False,
        )


    def getYears(self):
        years_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                )
        )


        if not self.local:
            # Do not serve local assets
            years_query = years_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        years_query = years_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_year.desc())


        year_choices = []
        for y in years_query:
            entry = (y.createDate_year, str(y.createDate_year))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        months_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                )
        )


        if not self.local:
            # Do not serve local assets
            months_query = months_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        months_query = months_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_month.desc())


        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.createDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.createDate_month, month_name)
            month_choices.append(entry)


        return month_choices


    def getDays(self, year, month):
        days_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                )
        )


        if not self.local:
            # Do not serve local assets
            days_query = days_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        days_query = days_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_day.desc())


        day_choices = []
        for d in days_query:
            entry = (d.createDate_day, str(d.createDate_day))
            day_choices.append(entry)


        return day_choices


    def getHours(self, year, month, day):
        hours_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
            IndiAllSkyDbImageTable.createDate_hour,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                )
        )


        if not self.local:
            # Do not serve local assets
            hours_query = hours_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        hours_query = hours_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_hour.desc())


        hour_choices = []
        for h in hours_query:
            entry = (h.createDate_hour, str(h.createDate_hour))
            hour_choices.append(entry)


        return hour_choices


    def getImages(self, year, month, day, hour):
        images_query = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                    IndiAllSkyDbImageTable.createDate_hour == hour,
                )
        )


        if not self.local:
            # Do not serve local assets
            images_query = images_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        images_query = images_query\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        image_rows = images_query.all()
        app.logger.info('Found %d images for image viewer', len(image_rows))

        diagnostic_assets = {}
        if self.asi676mc_diagnostic_download_enabled:
            diagnostic_assets = _asi676mc_diagnostic_assets(
                image_rows,
                self.camera_id,
                self.s3_prefix,
                self.local,
            )

        images_data = list()
        for img in image_rows:
            try:
                url = img.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue

            if img.detections:
                entry_str = '{0:s} [*]'.format(img.createDate.strftime('%H:%M:%S'))
            else:
                entry_str = img.createDate.strftime('%H:%M:%S')

            image_dict = dict()
            image_dict['id'] = img.id
            image_dict['url'] = str(url)
            image_dict['date'] = entry_str
            image_dict['ts'] = int(img.createDate.timestamp())
            image_dict['width'] = img.width
            image_dict['height'] = img.height
            image_dict['exclude'] = img.exclude


            # look for fits
            try:
                fits_images = db.session.query(
                    IndiAllSkyDbFitsImageTable,
                )\
                    .filter(IndiAllSkyDbFitsImageTable.camera_id == img.camera_id)\
                    .filter(IndiAllSkyDbFitsImageTable.createDate == img.createDate)\
                    .order_by(IndiAllSkyDbFitsImageTable.id.asc())\
                    .all()

                if not fits_images:
                    raise NoResultFound

                fits_image = next(
                    (
                        entry
                        for entry in fits_images
                        if not (entry.data or {}).get(
                            asi676mc.DIAGNOSTIC_METADATA_KEY
                        )
                    ),
                    None,
                )
                if fits_image is None:
                    raise NoResultFound

                image_dict['fits'] = str(fits_image.getUrl(s3_prefix=self.s3_prefix, local=self.local))
                image_dict['fits_id'] = fits_image.id
            except NoResultFound:
                image_dict['fits'] = None
                image_dict['fits_id'] = None

            image_diagnostic_assets = diagnostic_assets.get(img.id, {})
            image_dict['asi676mc_diagnostic_preceding_fits'] = (
                image_diagnostic_assets.get('preceding')
            )
            image_dict['asi676mc_diagnostic_bad_fits'] = (
                image_diagnostic_assets.get('bad')
            )
            image_dict['asi676mc_diagnostic_following_fits'] = (
                image_diagnostic_assets.get('following')
            )


            # look for raw exports
            try:
                raw_image = db.session.query(
                    IndiAllSkyDbRawImageTable,
                )\
                    .filter(IndiAllSkyDbRawImageTable.createDate == img.createDate)\
                    .one()

                image_dict['raw'] = str(raw_image.getUrl(s3_prefix=self.s3_prefix, local=self.local))
                image_dict['raw_id'] = raw_image.id
            except NoResultFound:
                image_dict['raw'] = None
                image_dict['raw_id'] = None
            except ValueError:
                # this can happen when RAW files are exported outside of the document root
                image_dict['raw'] = None
                image_dict['raw_id'] = None


            # look for panorama
            try:
                panorama_image = db.session.query(
                    IndiAllSkyDbPanoramaImageTable,
                )\
                    .filter(IndiAllSkyDbPanoramaImageTable.createDate == img.createDate)\
                    .one()

                image_dict['panorama'] = str(panorama_image.getUrl(s3_prefix=self.s3_prefix, local=self.local))
                image_dict['panorama_id'] = panorama_image.id
            except NoResultFound:
                image_dict['panorama'] = None
                image_dict['panorama_id'] = None


            images_data.append(image_dict)


        return images_data


class IndiAllskyImageViewerPreload(IndiAllskyImageViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyImageViewerPreload, self).__init__(*args, **kwargs)

        last_image = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                )
        )\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .first()

        if not last_image:
            app.logger.warning('No images found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)
            self.DAY_SELECT.choices = (('', 'None'),)
            self.HOUR_SELECT.choices = (('', 'None'),)
            self.IMG_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)
        self.DAY_SELECT.choices = (('', 'Loading'),)
        self.HOUR_SELECT.choices = (('', 'Loading'),)
        self.IMG_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


class IndiAllskyFitsImageViewer(FlaskForm):
    model = IndiAllSkyDbFitsImageTable

    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    DAY_SELECT           = SelectField('Day', choices=[], validators=[])
    HOUR_SELECT          = SelectField('Hour', choices=[], validators=[])
    IMG_SELECT           = SelectField('Image', choices=[], validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyFitsImageViewer, self).__init__(*args, **kwargs)

        self.camera_id = kwargs.get('camera_id')


    def getYears(self):
        years_query = db.session.query(
            self.model.createDate_year,
        )\
            .filter(self.model.camera_id == self.camera_id)


        years_query = years_query\
            .distinct()\
            .order_by(self.model.createDate_year.desc())


        year_choices = []
        for y in years_query:
            entry = (y.createDate_year, str(y.createDate_year))
            year_choices.append(entry)


        #app.logger.info('Years: %s', year_choices)

        return year_choices


    def getMonths(self, year):
        months_query = db.session.query(
            self.model.createDate_year,
            self.model.createDate_month,
        )\
            .filter(
                and_(
                    self.model.camera_id == self.camera_id,
                    self.model.createDate_year == year,
                )
        )


        months_query = months_query\
            .distinct()\
            .order_by(self.model.createDate_month.desc())


        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.createDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.createDate_month, month_name)
            month_choices.append(entry)


        return month_choices


    def getDays(self, year, month):
        days_query = db.session.query(
            self.model.createDate_year,
            self.model.createDate_month,
            self.model.createDate_day,
        )\
            .filter(
                and_(
                    self.model.camera_id == self.camera_id,
                    self.model.createDate_year == year,
                    self.model.createDate_month == month,
                )
        )


        days_query = days_query\
            .distinct()\
            .order_by(self.model.createDate_day.desc())


        day_choices = []
        for d in days_query:
            entry = (d.createDate_day, str(d.createDate_day))
            day_choices.append(entry)


        return day_choices


    def getHours(self, year, month, day):
        hours_query = db.session.query(
            self.model.createDate_year,
            self.model.createDate_month,
            self.model.createDate_day,
            self.model.createDate_hour,
        )\
            .filter(
                and_(
                    self.model.camera_id == self.camera_id,
                    self.model.createDate_year == year,
                    self.model.createDate_month == month,
                    self.model.createDate_day == day,
                )
        )


        hours_query = hours_query\
            .distinct()\
            .order_by(self.model.createDate_hour.desc())


        hour_choices = []
        for h in hours_query:
            entry = (h.createDate_hour, str(h.createDate_hour))
            hour_choices.append(entry)


        return hour_choices


    def getImages(self, year, month, day, hour):
        images_query = db.session.query(
            self.model,
        )\
            .filter(
                and_(
                    self.model.camera_id == self.camera_id,
                    self.model.createDate_year == year,
                    self.model.createDate_month == month,
                    self.model.createDate_day == day,
                    self.model.createDate_hour == hour,
                )
        )


        images_query = images_query\
            .order_by(self.model.createDate.desc())


        app.logger.info('Found %d FITS images', images_query.count())

        images_data = list()
        for img in images_query:
            url = url_for('indi_allsky.fits2jpeg_view', id=img.id)

            entry_str = img.createDate.strftime('%H:%M:%S')
            diagnostic_metadata = (img.data or {}).get(
                asi676mc.DIAGNOSTIC_METADATA_KEY,
                {},
            )
            diagnostic_roles = diagnostic_metadata.get('roles', [])
            if diagnostic_roles:
                role_names = '/'.join(role['role'] for role in diagnostic_roles)
                entry_str = '{0:s} [ASI676MC {1:s}]'.format(
                    entry_str,
                    role_names,
                )

            fits_url = img.getUrl(local=True)

            image_dict = dict()
            image_dict['id'] = img.id
            image_dict['url'] = str(url)
            image_dict['fits'] = str(fits_url)
            image_dict['date'] = entry_str
            image_dict['ts'] = int(img.createDate.timestamp())
            image_dict['width'] = img.width
            image_dict['height'] = img.height


            images_data.append(image_dict)


        return images_data


class IndiAllskyFitsImageViewerPreload(IndiAllskyFitsImageViewer):

    def __init__(self, *args, **kwargs):
        super(IndiAllskyFitsImageViewerPreload, self).__init__(*args, **kwargs)

        last_fits_image = db.session.query(
            self.model,
        )\
            .filter(self.model.camera_id == self.camera_id)\
            .order_by(self.model.createDate.desc())\
            .first()

        if not last_fits_image:
            app.logger.warning('No images found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)
            self.DAY_SELECT.choices = (('', 'None'),)
            self.HOUR_SELECT.choices = (('', 'None'),)
            self.IMG_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)
        self.DAY_SELECT.choices = (('', 'Loading'),)
        self.HOUR_SELECT.choices = (('', 'Loading'),)
        self.IMG_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


class IndiAllskyGalleryViewer(FlaskForm):
    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    DAY_SELECT           = SelectField('Day', choices=[], validators=[])
    HOUR_SELECT          = SelectField('Hour', choices=[], validators=[])
    FILTER_DETECTIONS    = BooleanField('Detections')
    FILTER_ASI676MC_REPAIRED = BooleanField('Purple frame repaired')
    FILTER_ASI676MC_EXCLUDED = BooleanField('Purple frame excluded')
    FILTER_ASI676MC_FAILED = BooleanField('Purple-frame repair failed')


    def __init__(self, *args, **kwargs):
        super(IndiAllskyGalleryViewer, self).__init__(*args, **kwargs)

        self.detections_count = kwargs.get('detections_count', 0)
        self.s3_prefix = kwargs.get('s3_prefix', '')
        self.camera_id = kwargs.get('camera_id')
        self.local = kwargs.get('local')
        requested_statuses = kwargs.get('asi676mc_statuses', ())
        self.asi676mc_statuses = tuple(
            status
            for status in requested_statuses
            if status in asi676mc.DIAGNOSTIC_BAD_STATUSES
        )


    def _apply_asi676mc_status_filter(self, query):
        """Limit one gallery query to selected purple-frame outcomes."""
        if not self.asi676mc_statuses:
            return query

        return query.filter(
            IndiAllSkyDbImageTable.data['asi676mc_repair_status']
            .as_string()
            .in_(self.asi676mc_statuses)
        )


    def getYears(self):
        years_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                )
        )

        years_query = self._apply_asi676mc_status_filter(years_query)


        ### Disable this join to make things faster
        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        if not self.local:
            # Do not serve local assets
            years_query = years_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        years_query = years_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_year.desc())


        year_choices = []
        for y in years_query:
            entry = (y.createDate_year, str(y.createDate_year))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        months_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                )
        )

        months_query = self._apply_asi676mc_status_filter(months_query)

        ### Disable this join to make things faster
        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        if not self.local:
            # Do not serve local assets
            months_query = months_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        months_query = months_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_month.desc())


        month_choices = []
        for m in months_query:
            month_name = datetime.strptime('{0} {1}'.format(year, m.createDate_month), '%Y %m')\
                .strftime('%B')
            entry = (m.createDate_month, month_name)
            month_choices.append(entry)


        return month_choices


    def getDays(self, year, month):
        days_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                )
        )

        days_query = self._apply_asi676mc_status_filter(days_query)


        ### Disable this join to make things faster
        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        if not self.local:
            # Do not serve local assets
            days_query = days_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        days_query = days_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_day.desc())


        day_choices = []
        for d in days_query:
            entry = (d.createDate_day, str(d.createDate_day))
            day_choices.append(entry)


        return day_choices


    def getHours(self, year, month, day):
        hours_query = db.session.query(
            IndiAllSkyDbImageTable.createDate_year,
            IndiAllSkyDbImageTable.createDate_month,
            IndiAllSkyDbImageTable.createDate_day,
            IndiAllSkyDbImageTable.createDate_hour,
        )\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                )
        )

        hours_query = self._apply_asi676mc_status_filter(hours_query)


        ### Disable this join to make things faster
        #    .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\


        if not self.local:
            # Do not serve local assets
            hours_query = hours_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        hours_query = hours_query\
            .distinct()\
            .order_by(IndiAllSkyDbImageTable.createDate_hour.desc())


        hour_choices = []
        for h in hours_query:
            entry = (h.createDate_hour, str(h.createDate_hour))
            hour_choices.append(entry)


        return hour_choices


    def getImages(self, year, month, day, hour):
        images_query = db.session.query(
            IndiAllSkyDbImageTable,
            IndiAllSkyDbThumbnailTable,
        )\
            .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\
            .filter(
                and_(
                    IndiAllSkyDbImageTable.camera_id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                    IndiAllSkyDbImageTable.createDate_year == year,
                    IndiAllSkyDbImageTable.createDate_month == month,
                    IndiAllSkyDbImageTable.createDate_day == day,
                    IndiAllSkyDbImageTable.createDate_hour == hour,
                )
        )

        images_query = self._apply_asi676mc_status_filter(images_query)


        if not self.local:
            # Do not serve local assets
            images_query = images_query\
                .filter(
                    or_(
                        IndiAllSkyDbImageTable.remote_url != sa_null(),
                        IndiAllSkyDbImageTable.s3_key != sa_null(),
                    )
                )


        images_query = images_query\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        image_rows = images_query.all()
        app.logger.info('Found %d images for gallery', len(image_rows))

        images_data = list()
        for img, thumb in image_rows:
            try:
                image_url = img.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                thumbnail_url = thumb.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue


            image_dict = dict()
            image_dict['id'] = img.id
            image_dict['date'] = img.createDate.strftime('%H:%M:%S')
            image_dict['url'] = str(image_url)
            image_dict['width'] = img.width
            image_dict['height'] = img.height
            image_dict['exclude'] = img.exclude
            image_dict['ts'] = int(img.createDate.timestamp())
            image_dict['thumbnail_url'] = str(thumbnail_url)
            image_dict['thumbnail_width'] = thumb.width
            image_dict['thumbnail_height'] = thumb.height

            image_metadata = img.data or {}
            repair_metadata = image_metadata.get('asi676mc_repair', {})
            repair_status = image_metadata.get(
                'asi676mc_repair_status',
                repair_metadata.get('status'),
            )
            image_dict['asi676mc_repair_status'] = repair_status

            signature_before = repair_metadata.get('signature_before') or {}
            signature_after = repair_metadata.get('signature_after') or {}
            image_dict['asi676mc_purple_ratio_before'] = signature_before.get('purple_ratio')
            image_dict['asi676mc_purple_ratio_after'] = signature_after.get('purple_ratio')

            images_data.append(image_dict)


        return images_data


class IndiAllskyGalleryViewerPreload(IndiAllskyGalleryViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyGalleryViewerPreload, self).__init__(*args, **kwargs)

        last_image = db.session.query(
            IndiAllSkyDbImageTable,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .join(IndiAllSkyDbThumbnailTable, IndiAllSkyDbImageTable.thumbnail_uuid == IndiAllSkyDbThumbnailTable.uuid)\
            .filter(
                and_(
                    IndiAllSkyDbCameraTable.id == self.camera_id,
                    IndiAllSkyDbImageTable.detections >= self.detections_count,
                )
        )\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .first()


        if not last_image:
            app.logger.warning('No images found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)
            self.DAY_SELECT.choices = (('', 'None'),)
            self.HOUR_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)
        self.DAY_SELECT.choices = (('', 'Loading'),)
        self.HOUR_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


class IndiAllskyVideoViewer(FlaskForm):
    TIMEOFDAY_SELECT_choices = (
        ('all', 'All'),
        ('day', 'Day'),
        ('night', 'Night'),
    )

    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])
    TIMEOFDAY_SELECT     = SelectField('Time of Day', choices=TIMEOFDAY_SELECT_choices, validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyVideoViewer, self).__init__(*args, **kwargs)

        self.s3_prefix = kwargs.get('s3_prefix', '')
        self.camera_id = kwargs.get('camera_id')
        self.local = kwargs.get('local')


    def getYears(self):
        year_col = func.coalesce(
            IndiAllSkyDbVideoTable.dayDate_year,
            extract('year', IndiAllSkyDbVideoTable.dayDate),
        ).label('year_val')

        years_query = db.session.query(year_col)\
            .filter(IndiAllSkyDbVideoTable.camera_id == self.camera_id)


        if not self.local:
            # Do not serve local assets
            years_query = years_query\
                .filter(
                    or_(
                        IndiAllSkyDbVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbVideoTable.s3_key != sa_null(),
                    )
                )


        years_query = years_query\
            .distinct()\
            .order_by(year_col.desc())


        year_choices = []
        for y in years_query:
            if y.year_val is None:
                continue
            year_val = int(y.year_val)
            entry = (year_val, str(year_val))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        year_col = func.coalesce(
            IndiAllSkyDbVideoTable.dayDate_year,
            extract('year', IndiAllSkyDbVideoTable.dayDate),
        )
        month_col = func.coalesce(
            IndiAllSkyDbVideoTable.dayDate_month,
            extract('month', IndiAllSkyDbVideoTable.dayDate),
        ).label('month_val')

        months_query = db.session.query(month_col)\
            .filter(
                and_(
                    IndiAllSkyDbVideoTable.camera_id == self.camera_id,
                    year_col == year,
                )
        )


        if not self.local:
            # Do not serve local assets
            months_query = months_query\
                .filter(
                    or_(
                        IndiAllSkyDbVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbVideoTable.s3_key != sa_null(),
                    )
                )


        months_query = months_query\
            .distinct()\
            .order_by(month_col.desc())


        month_choices = []
        for m in months_query:
            if m.month_val is None:
                continue
            month_val = int(m.month_val)
            month_name = datetime.strptime('{0} {1}'.format(year, month_val), '%Y %m')\
                .strftime('%B')
            entry = (month_val, month_name)
            month_choices.append(entry)


        return month_choices


    def getVideos(self, year, month, timeofday):
        year_col = func.coalesce(
            IndiAllSkyDbVideoTable.dayDate_year,
            extract('year', IndiAllSkyDbVideoTable.dayDate),
        )
        month_col = func.coalesce(
            IndiAllSkyDbVideoTable.dayDate_month,
            extract('month', IndiAllSkyDbVideoTable.dayDate),
        )

        videos_query = IndiAllSkyDbVideoTable.query\
            .filter(
                and_(
                    IndiAllSkyDbVideoTable.camera_id == self.camera_id,
                    year_col == year,
                    month_col == month,
                )
            )


        # add time of day filter
        if timeofday == 'day':
            videos_query = videos_query.filter(IndiAllSkyDbVideoTable.night == sa_false())
        elif timeofday == 'night':
            videos_query = videos_query.filter(IndiAllSkyDbVideoTable.night == sa_true())
        else:
            pass


        if not self.local:
            # Do not serve local assets
            videos_query = videos_query\
                .filter(
                    or_(
                        IndiAllSkyDbVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbVideoTable.s3_key != sa_null(),
                    )
                )


        # set order
        videos_query = videos_query.order_by(
            IndiAllSkyDbVideoTable.dayDate.desc(),
            IndiAllSkyDbVideoTable.night.desc(),
            IndiAllSkyDbVideoTable.createDate.desc(),  # there should only be one, but just in case
        )


        app.logger.info('Found %d timelapses', videos_query.count())

        videos_data = []
        for v in videos_query:
            try:
                url = v.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue


            if v.data:
                data = v.data
            else:
                data = {}

            entry = {
                'id'                : v.id,
                'url'               : str(url),
                'success'           : v.success,
                'dayDate_long'      : v.dayDate.strftime('%B %d, %Y'),
                'dayDate'           : v.dayDate.strftime('%Y%m%d'),
                'night'             : v.night,
                'max_smoke_rating'  : constants.SMOKE_RATING_MAP_STR[data.get('max_smoke_rating', constants.SMOKE_RATING_NODATA)],
                'max_kpindex'       : data.get('max_kpindex', 0.0),
                'max_ovation_max'   : data.get('max_ovation_max', 0),
                'max_moonphase'     : data.get('max_moonphase', 0),  # might be null
                'max_stars'         : int(data.get('max_stars', 0)),
                'avg_stars'         : int(data.get('avg_stars', 0)),
                'avg_sqm'           : int(data.get('avg_sqm', 0)),
                'youtube_uploaded'  : bool(data.get('youtube_id', False)),
            }
            videos_data.append(entry)

        # cannot query the DB from inside the DB query
        for entry in videos_data:
            dayDate = datetime.strptime(entry['dayDate'], '%Y%m%d').date()

            # Querying the oldest due to a bug where regeneated files are added with the wrong dayDate
            # fix is inbound

            ### Keogram
            keogram_entry_q = IndiAllSkyDbKeogramTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbKeogramTable.camera_id == self.camera_id,
                        IndiAllSkyDbKeogramTable.dayDate == dayDate,
                        IndiAllSkyDbKeogramTable.night == entry['night'],
                    )
                )


            if not self.local:
                # Do not serve local assets
                keogram_entry_q = keogram_entry_q\
                    .filter(
                        or_(
                            IndiAllSkyDbKeogramTable.remote_url != sa_null(),
                            IndiAllSkyDbKeogramTable.s3_key != sa_null(),
                        )
                    )


            keogram_entry = keogram_entry_q\
                .order_by(IndiAllSkyDbKeogramTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if keogram_entry:
                try:
                    keogram_url = keogram_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                    keogram_id = keogram_entry.id
                    keogram_success = keogram_entry.success
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    keogram_url = None
                    keogram_id = 0
                    keogram_success = False


                if keogram_entry.thumbnail_uuid:
                    keogram_thumbnail_entry = IndiAllSkyDbThumbnailTable.query\
                        .filter(IndiAllSkyDbThumbnailTable.uuid == keogram_entry.thumbnail_uuid)\
                        .first()

                    if keogram_thumbnail_entry:
                        try:
                            keogram_thumbnail_url = keogram_thumbnail_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                        except ValueError:
                            keogram_thumbnail_url = None
                    else:
                        keogram_thumbnail_url = None
                else:
                    keogram_thumbnail_url = None
            else:
                keogram_url = None
                keogram_id = -1
                keogram_thumbnail_url = None
                keogram_success = False


            ### Star trail
            startrail_entry_q = IndiAllSkyDbStarTrailsTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbStarTrailsTable.camera_id == self.camera_id,
                        IndiAllSkyDbStarTrailsTable.dayDate == dayDate,
                        IndiAllSkyDbStarTrailsTable.night == entry['night'],
                    )
                )


            if not self.local:
                # Do not serve local assets
                startrail_entry_q = startrail_entry_q\
                    .filter(
                        or_(
                            IndiAllSkyDbStarTrailsTable.remote_url != sa_null(),
                            IndiAllSkyDbStarTrailsTable.s3_key != sa_null(),
                        )
                    )


            startrail_entry = startrail_entry_q\
                .order_by(IndiAllSkyDbStarTrailsTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if startrail_entry:
                try:
                    startrail_url = startrail_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                    startrail_id = startrail_entry.id
                    startrail_success = startrail_entry.success
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    startrail_url = None
                    startrail_id = -1
                    startrail_success = False


                if startrail_entry.thumbnail_uuid:
                    startrail_thumbnail_entry = IndiAllSkyDbThumbnailTable.query\
                        .filter(IndiAllSkyDbThumbnailTable.uuid == startrail_entry.thumbnail_uuid)\
                        .first()

                    if startrail_thumbnail_entry:
                        try:
                            startrail_thumbnail_url = startrail_thumbnail_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                        except ValueError:
                            startrail_thumbnail_url = None
                    else:
                        startrail_thumbnail_url = None
                else:
                    startrail_thumbnail_url = None
            else:
                startrail_url = None
                startrail_id = -1
                startrail_thumbnail_url = None
                startrail_success = False


            ### Star trail timelapses
            startrail_video_entry_q = IndiAllSkyDbStarTrailsVideoTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbStarTrailsVideoTable.camera_id == self.camera_id,
                        IndiAllSkyDbStarTrailsVideoTable.dayDate == dayDate,
                        IndiAllSkyDbStarTrailsVideoTable.night == entry['night'],
                    )
                )


            if not self.local:
                # Do not serve local assets
                startrail_video_entry_q = startrail_video_entry_q\
                    .filter(
                        or_(
                            IndiAllSkyDbStarTrailsVideoTable.remote_url != sa_null(),
                            IndiAllSkyDbStarTrailsVideoTable.s3_key != sa_null(),
                        )
                    )


            startrail_video_entry = startrail_video_entry_q\
                .order_by(IndiAllSkyDbStarTrailsVideoTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if startrail_video_entry:
                if startrail_video_entry.data:
                    st_v_data = startrail_video_entry.data
                else:
                    st_v_data = {}

                try:
                    startrail_video_url = startrail_video_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                    startrail_video_id = startrail_video_entry.id
                    startrail_video_youtube = bool(st_v_data.get('youtube_id', False))
                    startrail_video_success = startrail_video_entry.success
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    startrail_video_url = None
                    startrail_video_id = -1
                    startrail_video_youtube = False
                    startrail_video_success = False
            else:
                startrail_video_url = None
                startrail_video_id = -1
                startrail_video_youtube = False
                startrail_video_success = False


            ### Panorama timelapses
            panorama_video_entry_q = IndiAllSkyDbPanoramaVideoTable.query\
                .filter(
                    and_(
                        IndiAllSkyDbPanoramaVideoTable.camera_id == self.camera_id,
                        IndiAllSkyDbPanoramaVideoTable.dayDate == dayDate,
                        IndiAllSkyDbPanoramaVideoTable.night == entry['night'],
                    )
                )


            if not self.local:
                # Do not serve local assets
                panorama_video_entry_q = panorama_video_entry_q\
                    .filter(
                        or_(
                            IndiAllSkyDbPanoramaVideoTable.remote_url != sa_null(),
                            IndiAllSkyDbPanoramaVideoTable.s3_key != sa_null(),
                        )
                    )


            panorama_video_entry = panorama_video_entry_q\
                .order_by(IndiAllSkyDbPanoramaVideoTable.dayDate.asc())\
                .first()  # use the oldest (asc)


            if panorama_video_entry:
                if panorama_video_entry.data:
                    p_v_data = panorama_video_entry.data
                else:
                    p_v_data = {}

                try:
                    panorama_video_url = panorama_video_entry.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                    panorama_video_id = panorama_video_entry.id
                    panorama_video_youtube = bool(p_v_data.get('youtube_id', False))
                    panorama_video_success = panorama_video_entry.success
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    panorama_video_url = None
                    panorama_video_id = -1
                    panorama_video_youtube = False
                    panorama_video_success = False
            else:
                panorama_video_url = None
                panorama_video_id = -1
                panorama_video_youtube = False
                panorama_video_success = False


            entry['keogram']    = str(keogram_url)
            entry['keogram_id'] = keogram_id
            entry['keogram_thumbnail']  = str(keogram_thumbnail_url)
            entry['keogram_success']  = keogram_success
            entry['startrail']  = str(startrail_url)
            entry['startrail_thumbnail']  = str(startrail_thumbnail_url)
            entry['startrail_id']  = startrail_id
            entry['startrail_success']  = startrail_success
            entry['startrail_timelapse']  = str(startrail_video_url)
            entry['startrail_timelapse_id']  = startrail_video_id
            entry['startrail_timelapse_youtube_uploaded']  = startrail_video_youtube
            entry['startrail_timelapse_success']  = startrail_video_success
            entry['panorama_timelapse']  = str(panorama_video_url)
            entry['panorama_timelapse_id']  = panorama_video_id
            entry['panorama_timelapse_youtube_uploaded']  = panorama_video_youtube
            entry['panorama_timelapse_success']  = panorama_video_success


        return videos_data


class IndiAllskyVideoViewerPreload(IndiAllskyVideoViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyVideoViewerPreload, self).__init__(*args, **kwargs)

        last_video = IndiAllSkyDbVideoTable.query\
            .filter(IndiAllSkyDbVideoTable.camera_id == self.camera_id)\
            .order_by(IndiAllSkyDbVideoTable.dayDate.desc())\
            .first()

        if not last_video:
            app.logger.warning('No timelapses found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


class IndiAllskyMiniVideoViewer(FlaskForm):
    CAMERA_ID            = HiddenField('Camera ID', validators=[DataRequired()])
    YEAR_SELECT          = SelectField('Year', choices=[], validators=[])
    MONTH_SELECT         = SelectField('Month', choices=[], validators=[])


    def __init__(self, *args, **kwargs):
        super(IndiAllskyMiniVideoViewer, self).__init__(*args, **kwargs)

        self.s3_prefix = kwargs.get('s3_prefix', '')
        self.camera_id = kwargs.get('camera_id')
        self.local = kwargs.get('local')


    def getYears(self):
        year_col = func.coalesce(
            IndiAllSkyDbMiniVideoTable.dayDate_year,
            extract('year', IndiAllSkyDbMiniVideoTable.dayDate),
        ).label('year_val')

        years_query = db.session.query(year_col)\
            .filter(IndiAllSkyDbMiniVideoTable.camera_id == self.camera_id)


        if not self.local:
            # Do not serve local assets
            years_query = years_query\
                .filter(
                    or_(
                        IndiAllSkyDbMiniVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbMiniVideoTable.s3_key != sa_null(),
                    )
                )


        years_query = years_query\
            .distinct()\
            .order_by(year_col.desc())


        year_choices = []
        for y in years_query:
            if y.year_val is None:
                continue
            year_val = int(y.year_val)
            entry = (year_val, str(year_val))
            year_choices.append(entry)


        return year_choices


    def getMonths(self, year):
        year_col = func.coalesce(
            IndiAllSkyDbMiniVideoTable.dayDate_year,
            extract('year', IndiAllSkyDbMiniVideoTable.dayDate),
        )
        month_col = func.coalesce(
            IndiAllSkyDbMiniVideoTable.dayDate_month,
            extract('month', IndiAllSkyDbMiniVideoTable.dayDate),
        ).label('month_val')

        months_query = db.session.query(month_col)\
            .filter(
                and_(
                    IndiAllSkyDbMiniVideoTable.camera_id == self.camera_id,
                    year_col == year,
                )
        )


        if not self.local:
            # Do not serve local assets
            months_query = months_query\
                .filter(
                    or_(
                        IndiAllSkyDbMiniVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbMiniVideoTable.s3_key != sa_null(),
                    )
                )


        months_query = months_query\
            .distinct()\
            .order_by(month_col.desc())


        month_choices = []
        for m in months_query:
            if m.month_val is None:
                continue
            month_val = int(m.month_val)
            month_name = datetime.strptime('{0} {1}'.format(year, month_val), '%Y %m')\
                .strftime('%B')
            entry = (month_val, month_name)
            month_choices.append(entry)


        return month_choices



    def getVideos(self, year, month):
        year_col = func.coalesce(
            IndiAllSkyDbMiniVideoTable.dayDate_year,
            extract('year', IndiAllSkyDbMiniVideoTable.dayDate),
        )
        month_col = func.coalesce(
            IndiAllSkyDbMiniVideoTable.dayDate_month,
            extract('month', IndiAllSkyDbMiniVideoTable.dayDate),
        )

        videos_query = db.session.query(
            IndiAllSkyDbMiniVideoTable,
        )\
            .filter(
                and_(
                    IndiAllSkyDbMiniVideoTable.camera_id == self.camera_id,
                    year_col == year,
                    month_col == month,
                )
        )


        if not self.local:
            # Do not serve local assets
            videos_query = videos_query\
                .filter(
                    or_(
                        IndiAllSkyDbMiniVideoTable.remote_url != sa_null(),
                        IndiAllSkyDbMiniVideoTable.s3_key != sa_null(),
                    )
                )


        # set order
        videos_query = videos_query.order_by(
            IndiAllSkyDbMiniVideoTable.dayDate.desc(),
            IndiAllSkyDbMiniVideoTable.night.desc(),
        )


        app.logger.info('Found %d mini-timelapses', videos_query.count())

        videos_data = []
        for v in videos_query:
            try:
                url = v.getUrl(s3_prefix=self.s3_prefix, local=self.local)
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue


            thumbnail = db.session.query(
                IndiAllSkyDbThumbnailTable,
            )\
                .filter(IndiAllSkyDbThumbnailTable.uuid == v.thumbnail_uuid)\
                .first()


            if thumbnail:
                try:
                    thumbnail_url = thumbnail.getUrl(s3_prefix=self.s3_prefix, local=self.local)
                except ValueError as e:
                    app.logger.error('Error determining relative file name: %s', str(e))
                    continue
            else:
                thumbnail_url = ''


            if v.data:
                data = v.data
            else:
                data = {}

            entry = {
                'id'                : v.id,
                'url'               : str(url),
                'success'           : v.success,
                'source'            : data.get('source', 'standard'),
                'thumbnail_url'     : str(thumbnail_url),
                'dayDate_long'      : v.dayDate.strftime('%B %d, %Y'),
                'dayDate'           : v.dayDate.strftime('%Y%m%d'),
                'night'             : v.night,
                'note'              : v.note,
                'max_smoke_rating'  : constants.SMOKE_RATING_MAP_STR[data.get('max_smoke_rating', constants.SMOKE_RATING_NODATA)],
                'max_kpindex'       : data.get('max_kpindex', 0.0),
                'max_ovation_max'   : data.get('max_ovation_max', 0),
                'max_moonphase'     : data.get('max_moonphase', 0),  # might be null
                'max_stars'         : int(data.get('max_stars', 0)),
                'avg_stars'         : int(data.get('avg_stars', 0)),
                'avg_sqm'           : int(data.get('avg_sqm', 0)),
                'youtube_uploaded'  : bool(data.get('youtube_id', False)),
            }
            videos_data.append(entry)


        return videos_data


class IndiAllskyMiniVideoViewerPreload(IndiAllskyMiniVideoViewer):
    def __init__(self, *args, **kwargs):
        super(IndiAllskyMiniVideoViewerPreload, self).__init__(*args, **kwargs)

        last_video = IndiAllSkyDbMiniVideoTable.query\
            .filter(IndiAllSkyDbMiniVideoTable.camera_id == self.camera_id)\
            .order_by(IndiAllSkyDbMiniVideoTable.dayDate.desc())\
            .first()

        if not last_video:
            app.logger.warning('No timelapses found in DB')

            self.YEAR_SELECT.choices = (('', 'None'),)
            self.MONTH_SELECT.choices = (('', 'None'),)

            return


        dates_start = time.time()

        self.YEAR_SELECT.choices = self.getYears()
        self.MONTH_SELECT.choices = (('', 'Loading'),)

        dates_elapsed_s = time.time() - dates_start
        app.logger.info('Dates processed in %0.4f s', dates_elapsed_s)


