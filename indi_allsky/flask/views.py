import platform
from datetime import datetime
from datetime import timedelta
import io
import json
import time
import math
from pathlib import Path
from collections import OrderedDict
import socket
import psutil
import dbus
import pycurl
import paramiko
import paho.mqtt
import ccdproc

import ephem

# for version reporting
import PyIndi
import cv2
import numpy
import astropy
import flask

from flask import render_template
from flask import request
from flask import jsonify
from flask import Blueprint
from flask import send_from_directory
from flask.views import View

from flask import current_app as app

#from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbDarkFrameTable
from .models import IndiAllSkyDbTaskQueueTable

from .models import TaskQueueQueue
from .models import TaskQueueState

from sqlalchemy import func
#from sqlalchemy import extract
#from sqlalchemy.types import DateTime
from sqlalchemy.types import Integer
#from sqlalchemy.orm.exc import NoResultFound

from .forms import IndiAllskyConfigForm
from .forms import IndiAllskyImageViewer
from .forms import IndiAllskyImageViewerPreload
from .forms import IndiAllskyVideoViewer
from .forms import IndiAllskyVideoViewerPreload
from .forms import IndiAllskySystemInfoForm
from .forms import IndiAllskyHistoryForm


bp = Blueprint(
    'indi_allsky',
    __name__,
    template_folder='templates',
    static_folder='static',
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
    static_url_path='static',
)


#@bp.route('/')
#@bp.route('/index')
#def index():
#    return render_template('index.html')


class BaseView(View):
    def __init__(self, **kwargs):
        super(BaseView, self).__init__(**kwargs)

        self.indi_allsky_config = self.get_indi_allsky_config()


    def get_indi_allsky_config(self):
        with io.open(app.config['INDI_ALLSKY_CONFIG'], 'r') as f_config_file:
            try:
                indi_allsky_config = json.loads(f_config_file.read(), object_pairs_hook=OrderedDict)
            except json.JSONDecodeError as e:
                app.logger.error('Error decoding json: %s', str(e))
                return dict()

        return indi_allsky_config


    def get_indiallsky_pid(self):
        indi_allsky_pid_p = Path(app.config['INDI_ALLSKY_PID'])

        try:
            with io.open(str(indi_allsky_pid_p), 'r') as pid_f:
                pid = pid_f.readline()
                pid = pid.rstrip()

        except FileNotFoundError:
            return False
        except PermissionError:
            return None

        try:
            pid_int = int(pid)
        except ValueError:
            return None

        return pid_int


    def get_indi_allsky_status(self):
        pid = self.get_indiallsky_pid()

        if pid is None:
            return '<span class="text-warning">UNKNOWN</span>'

        if not pid:
            return '<span class="text-danger">DOWN</span>'

        if psutil.pid_exists(pid):
            return '<span class="text-success">RUNNING</span>'


        return '<span class="text-danger">DOWN</span>'


    def get_astrometric_info(self):
        if not self.indi_allsky_config:
            return dict()

        data = dict()

        utcnow = datetime.utcnow()  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(self.indi_allsky_config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.indi_allsky_config['LOCATION_LATITUDE'])

        sun = ephem.Sun()
        moon = ephem.Moon()

        obs.date = utcnow
        sun.compute(obs)
        moon.compute(obs)


        # sun
        sun_alt = math.degrees(sun.alt)
        data['sun_alt'] = sun_alt

        sun_transit_date = obs.next_transit(sun).datetime()
        sun_transit_delta = sun_transit_date - utcnow
        if sun_transit_delta.seconds < 43200:  # 12 hours
            #rising
            data['sun_rising_sign'] = '&nearr;'
        else:
            #setting
            data['sun_rising_sign'] = '&searr;'


        # moon
        moon_alt = math.degrees(moon.alt)
        data['moon_alt'] = moon_alt

        #moon phase
        moon_phase_percent = moon.moon_phase * 100.0
        data['moon_phase_percent'] = moon_phase_percent

        moon_transit_date = obs.next_transit(moon).datetime()
        moon_transit_delta = moon_transit_date - utcnow
        if moon_transit_delta.seconds < 43200:  # 12 hours
            #rising
            data['moon_rising_sign'] = '&nearr;'
        else:
            #setting
            data['moon_rising_sign'] = '&searr;'


        # day/night
        if sun_alt > self.indi_allsky_config['NIGHT_SUN_ALT_DEG']:
            data['mode'] = 'Day'
        else:
            data['mode'] = 'Night'



        sun_lon = ephem.Ecliptic(sun).lon
        moon_lon = ephem.Ecliptic(moon).lon
        sm_angle = (moon_lon - sun_lon) % math.tau


        moon_quarter = int(sm_angle * 4.0 // math.tau)

        if moon_quarter < 2:
            #0, 1
            data['moon_phase'] = 'Waxing'
        else:
            #2, 3
            data['moon_phase'] = 'Waning'



        cycle_percent = (sm_angle / math.tau) * 100
        data['cycle_percent'] = cycle_percent

        if cycle_percent <= 50:
            # waxing
            if moon_phase_percent >= 0 and moon_phase_percent < 15:
                data['moon_phase_sign'] = '🌑'
            elif moon_phase_percent >= 15 and moon_phase_percent < 35:
                data['moon_phase_sign'] = '🌒'
            elif moon_phase_percent >= 35 and moon_phase_percent < 65:
                data['moon_phase_sign'] = '🌓'
            elif moon_phase_percent >= 65 and moon_phase_percent < 85:
                data['moon_phase_sign'] = '🌔'
            elif moon_phase_percent >= 85 and moon_phase_percent <= 100:
                data['moon_phase_sign'] = '🌕'
        else:
            # waning
            if moon_phase_percent >= 85 and moon_phase_percent <= 100:
                data['moon_phase_sign'] = '🌕'
            elif moon_phase_percent >= 65 and moon_phase_percent < 85:
                data['moon_phase_sign'] = '🌖'
            elif moon_phase_percent >= 35 and moon_phase_percent < 65:
                data['moon_phase_sign'] = '🌗'
            elif moon_phase_percent >= 15 and moon_phase_percent < 35:
                data['moon_phase_sign'] = '🌘'
            elif moon_phase_percent >= 0 and moon_phase_percent < 15:
                data['moon_phase_sign'] = '🌑'


        #app.logger.info('Astrometric data: %s', data)

        return data


    def getLatestCamera(self):
        latest_camera = IndiAllSkyDbCameraTable.query\
            .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
            .first()

        return latest_camera.id


class TemplateView(BaseView):
    def __init__(self, template_name, **kwargs):
        super(TemplateView, self).__init__(**kwargs)

        self.template_name = template_name


    def render_template(self, context):
        return render_template(self.template_name, **context)


    def dispatch_request(self):
        context = self.get_context()
        return self.render_template(context)


    def get_context(self):
        context = {
            'indi_allsky_status' : self.get_indi_allsky_status(),
            'astrometric_data'   : self.get_astrometric_info(),
        }
        return context


class FormView(TemplateView):
    pass


class JsonView(BaseView):
    def dispatch_request(self):
        json_data = self.get_objects()
        return jsonify(json_data)

    def get_objects(self):
        raise NotImplementedError()



class IndexView(TemplateView):
    def get_context(self):
        context = super(IndexView, self).get_context()

        context['latest_image_uri'] = 'images/latest.{0}'.format(self.indi_allsky_config.get('IMAGE_FILE_TYPE', 'jpg'))

        return context


class CamerasView(TemplateView):
    def get_context(self):
        context = super(CamerasView, self).get_context()

        #connectDate_local = func.datetime(IndiAllSkyDbCameraTable.connectDate, 'localtime', type_=DateTime).label('connectDate_local')
        context['camera_list'] = IndiAllSkyDbCameraTable.query\
            .all()

        return context


class DarkFramesView(TemplateView):
    def get_context(self):
        context = super(DarkFramesView, self).get_context()

        #createDate_local = func.datetime(IndiAllSkyDbDarkFrameTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        darkframe_list = IndiAllSkyDbDarkFrameTable.query\
            .join(IndiAllSkyDbCameraTable)\
            .order_by(
                IndiAllSkyDbCameraTable.id.desc(),
                IndiAllSkyDbDarkFrameTable.gain.asc(),
                IndiAllSkyDbDarkFrameTable.exposure.asc(),
            )


        context['darkframe_list'] = darkframe_list
        return context



class ImageLagView(TemplateView):
    def get_context(self):
        context = super(ImageLagView, self).get_context()

        now_minus_3h = datetime.now() - timedelta(hours=3)

        createDate_s = func.strftime('%s', IndiAllSkyDbImageTable.createDate, type_=Integer)
        image_lag_list = IndiAllSkyDbImageTable.query\
            .add_columns(
                IndiAllSkyDbImageTable.id,
                IndiAllSkyDbImageTable.createDate,
                IndiAllSkyDbImageTable.exposure,
                IndiAllSkyDbImageTable.exp_elapsed,
                (createDate_s - func.lag(createDate_s).over(order_by=IndiAllSkyDbImageTable.createDate)).label('lag_diff'),
            )\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_3h)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .limit(50)
        # filter is just to make it faster


        context['image_lag_list'] = image_lag_list

        return context



class SqmView(TemplateView):
    pass


class ImageLoopView(TemplateView):
    def get_context(self):
        context = super(ImageLoopView, self).get_context()

        context['form_history'] = IndiAllskyHistoryForm()

        return context


class ViewerView(TemplateView):
    pass


class JsonImageLoopView(JsonView):
    def __init__(self, **kwargs):
        super(JsonImageLoopView, self).__init__(**kwargs)

        self.camera_id = self.getLatestCamera()
        self.history_seconds = 900
        self.sqm_history_minutes = 30
        self.stars_history_minutes = 30
        self.limit = 1000  # sanity check


    def get_objects(self):
        history_seconds = int(request.args.get('limit_s', self.history_seconds))
        self.limit = int(request.args.get('limit', self.limit))

        # sanity check
        if history_seconds > 86400:
            history_seconds = 86400

        data = {
            'image_list' : self.getLatestImages(history_seconds),
            'sqm_data'   : self.getSqmData(),
            'stars_data' : self.getStarsData(),
        }

        return data


    def getLatestImages(self, history_seconds):
        now_minus_seconds = datetime.now() - timedelta(seconds=history_seconds)

        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        latest_images = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_seconds)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .limit(self.limit)

        image_list = list()
        for i in latest_images:
            try:
                uri = i.getUri()
            except ValueError as e:
                app.logger.error('Error determining relative file name: %s', str(e))
                continue

            data = {
                'file'  : str(uri),
                'sqm'   : i.sqm,
                'stars' : i.stars,
            }

            image_list.append(data)

        return image_list


    def getSqmData(self):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.sqm_history_minutes)

        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        sqm_images = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.sqm).label('image_max_sqm'),
                func.min(IndiAllSkyDbImageTable.sqm).label('image_min_sqm'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_minutes)\
            .first()


        sqm_data = {
            'max' : sqm_images.image_max_sqm,
            'min' : sqm_images.image_min_sqm,
            'avg' : sqm_images.image_avg_sqm,
        }

        return sqm_data


    def getStarsData(self):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.stars_history_minutes)

        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        stars_images = IndiAllSkyDbImageTable.query\
            .add_columns(
                func.max(IndiAllSkyDbImageTable.stars).label('image_max_stars'),
                func.min(IndiAllSkyDbImageTable.stars).label('image_min_stars'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_minutes)\
            .first()


        stars_data = {
            'max' : stars_images.image_max_stars,
            'min' : stars_images.image_min_stars,
            'avg' : stars_images.image_avg_stars,
        }

        return stars_data


class ChartView(TemplateView):
    def get_context(self):
        context = super(ChartView, self).get_context()

        context['form_history'] = IndiAllskyHistoryForm()

        return context


class JsonChartView(JsonView):
    def __init__(self, **kwargs):
        super(JsonChartView, self).__init__(**kwargs)

        self.camera_id = self.getLatestCamera()
        self.chart_history_seconds = 900


    def get_objects(self):
        history_seconds = int(request.args.get('limit_s', self.chart_history_seconds))

        # safety, limit history to 1 day
        if history_seconds > 86400:
            history_seconds = 86400


        data = {
            'chart_data' : self.getChartData(history_seconds),
        }

        return data


    def getLatestCamera(self):
        latest_camera = IndiAllSkyDbCameraTable.query\
            .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
            .first()

        return latest_camera.id


    def getChartData(self, history_seconds):
        now_minus_seconds = datetime.now() - timedelta(seconds=history_seconds)

        #createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        chart_query = IndiAllSkyDbImageTable.query\
            .add_columns(
                IndiAllSkyDbImageTable.createDate,
                IndiAllSkyDbImageTable.sqm,
                func.avg(IndiAllSkyDbImageTable.stars).over(order_by=IndiAllSkyDbImageTable.createDate, rows=(-5, 0)).label('stars_rolling'),
                IndiAllSkyDbImageTable.temp,
                IndiAllSkyDbImageTable.exposure,
                (IndiAllSkyDbImageTable.sqm - func.lag(IndiAllSkyDbImageTable.sqm).over(order_by=IndiAllSkyDbImageTable.createDate)).label('sqm_diff'),
            )\
            .join(IndiAllSkyDbCameraTable)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_seconds)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        #app.logger.info('Chart SQL: %s', str(chart_query))

        chart_data = {
            'sqm'   : [],
            'sqm_d' : [],
            'stars' : [],
            'temp'  : [],
            'exp'   : [],
            'histogram' : {
                'red'   : [],
                'green' : [],
                'blue'  : [],
                'gray'  : [],
            },
        }
        for i in chart_query:
            sqm_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : i.sqm,
            }
            chart_data['sqm'].append(sqm_data)

            star_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : int(i.stars_rolling),
            }
            chart_data['stars'].append(star_data)


            if self.indi_allsky_config.get('TEMP_DISPLAY') == 'f':
                sensortemp = ((i.temp * 9.0) / 5.0) + 32
            elif self.indi_allsky_config.get('TEMP_DISPLAY') == 'k':
                sensortemp = i.temp + 273.15
            else:
                sensortemp = i.temp

            temp_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : sensortemp,
            }
            chart_data['temp'].append(temp_data)

            exp_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : i.exposure,
            }
            chart_data['exp'].append(exp_data)

            sqm_d_data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : i.sqm_diff,
            }

            chart_data['sqm_d'].append(sqm_d_data)



        # build last image histogram
        now_minus_seconds = datetime.now() - timedelta(seconds=history_seconds)

        latest_image = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_seconds)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .first()


        if not latest_image:
            return chart_data


        latest_image_p = Path(latest_image.filename)
        if not latest_image_p.exists():
            app.logger.error('Image does not exist: %s', latest_image_p)
            return chart_data


        image_start = time.time()

        image_data = cv2.imread(str(latest_image_p), cv2.IMREAD_UNCHANGED)

        if isinstance(image_data, type(None)):
            app.logger.error('Unable to read %s', latest_image_p)
            return chart_data

        image_elapsed_s = time.time() - image_start
        app.logger.info('Image read in %0.4f s', image_elapsed_s)


        image_height, image_width = image_data.shape[:2]
        app.logger.info('Calculating histogram from RoI')

        mask = numpy.zeros(image_data.shape[:2], numpy.uint8)

        x1 = int((image_width / 2) - (image_width / 3))
        y1 = int((image_height / 2) - (image_height / 3))
        x2 = int((image_width / 2) + (image_width / 3))
        y2 = int((image_height / 2) + (image_height / 3))

        mask[y1:y2, x1:x2] = 255


        if len(image_data.shape) == 2:
            # mono
            h_numpy = cv2.calcHist([image_data], [0], mask, [256], [0, 256])
            for x, val in enumerate(h_numpy.tolist()):
                h_data = {
                    'x' : str(x),
                    'y' : val[0],
                }
                chart_data['histogram']['gray'].append(h_data)

        else:
            # color
            color = ('blue', 'green', 'red')
            for i, col in enumerate(color):
                h_numpy = cv2.calcHist([image_data], [i], mask, [256], [0, 256])
                for x, val in enumerate(h_numpy.tolist()):
                    h_data = {
                        'x' : str(x),
                        'y' : val[0],
                    }
                    chart_data['histogram'][col].append(h_data)


        return chart_data


class ConfigView(FormView):
    def get_context(self):
        context = super(ConfigView, self).get_context()

        form_data = {
            'INDI_SERVER'                    : self.indi_allsky_config.get('INDI_SERVER', 'localhost'),
            'INDI_PORT'                      : self.indi_allsky_config.get('INDI_PORT', 7624),
            'CCD_CONFIG__NIGHT__GAIN'        : self.indi_allsky_config.get('CCD_CONFIG', {}).get('NIGHT', {}).get('GAIN', 100),
            'CCD_CONFIG__NIGHT__BINNING'     : self.indi_allsky_config.get('CCD_CONFIG', {}).get('NIGHT', {}).get('BINNING', 1),
            'CCD_CONFIG__MOONMODE__GAIN'     : self.indi_allsky_config.get('CCD_CONFIG', {}).get('MOONMODE', {}).get('GAIN', 75),
            'CCD_CONFIG__MOONMODE__BINNING'  : self.indi_allsky_config.get('CCD_CONFIG', {}).get('MOONMODE', {}).get('BINNING', 1),
            'CCD_CONFIG__DAY__GAIN'          : self.indi_allsky_config.get('CCD_CONFIG', {}).get('DAY', {}).get('GAIN', 0),
            'CCD_CONFIG__DAY__BINNING'       : self.indi_allsky_config.get('CCD_CONFIG', {}).get('DAY', {}).get('BINNING', 1),
            'CCD_EXPOSURE_MAX'               : self.indi_allsky_config.get('CCD_EXPOSURE_MAX', 15.0),
            'CCD_EXPOSURE_DEF'               : self.indi_allsky_config.get('CCD_EXPOSURE_DEF', 0.0),
            'CCD_EXPOSURE_MIN'               : self.indi_allsky_config.get('CCD_EXPOSURE_MIN', 0.0),
            'EXPOSURE_PERIOD'                : self.indi_allsky_config.get('CCD_EXPOSURE_PERIOD', 15.0),
            'AUTO_WB'                        : self.indi_allsky_config.get('AUTO_WB', False),
            'TEMP_DISPLAY'                   : self.indi_allsky_config.get('TEMP_DISPLAY', 'c'),
            'TARGET_ADU'                     : self.indi_allsky_config.get('TARGET_ADU', 75),
            'TARGET_ADU_DEV'                 : self.indi_allsky_config.get('TARGET_ADU_DEV', 10),
            'DETECT_STARS'                   : self.indi_allsky_config.get('DETECT_STARS', True),
            'LOCATION_LATITUDE'              : self.indi_allsky_config.get('LOCATION_LATITUDE', 0.0),
            'LOCATION_LONGITUDE'             : self.indi_allsky_config.get('LOCATION_LONGITUDE', 0.0),
            'TIMELAPSE_ENABLE'               : self.indi_allsky_config.get('TIMELAPSE_ENABLE', True),
            'DAYTIME_CAPTURE'                : self.indi_allsky_config.get('DAYTIME_CAPTURE', False),
            'DAYTIME_TIMELAPSE'              : self.indi_allsky_config.get('DAYTIME_TIMELAPSE', True),
            'DAYTIME_CONTRAST_ENHANCE'       : self.indi_allsky_config.get('DAYTIME_CONTRAST_ENHANCE', False),
            'NIGHT_CONTRAST_ENHANCE'         : self.indi_allsky_config.get('NIGHT_CONTRAST_ENHANCE', False),
            'NIGHT_SUN_ALT_DEG'              : self.indi_allsky_config.get('NIGHT_SUN_ALT_DEG', -6.0),
            'NIGHT_MOONMODE_ALT_DEG'         : self.indi_allsky_config.get('NIGHT_MOONMODE_ALT_DEG', 5.0),
            'NIGHT_MOONMODE_PHASE'           : self.indi_allsky_config.get('NIGHT_MOONMODE_PHASE', 50.0),
            'KEOGRAM_ANGLE'                  : self.indi_allsky_config.get('KEOGRAM_ANGLE', 0.0),
            'KEOGRAM_H_SCALE'                : self.indi_allsky_config.get('KEOGRAM_H_SCALE', 100),
            'KEOGRAM_V_SCALE'                : self.indi_allsky_config.get('KEOGRAM_V_SCALE', 33),
            'KEOGRAM_LABEL'                  : self.indi_allsky_config.get('KEOGRAM_LABEL', True),
            'STARTRAILS_MAX_ADU'             : self.indi_allsky_config.get('STARTRAILS_MAX_ADU', 50),
            'STARTRAILS_MASK_THOLD'          : self.indi_allsky_config.get('STARTRAILS_MASK_THOLD', 190),
            'STARTRAILS_PIXEL_THOLD'         : self.indi_allsky_config.get('STARTRAILS_PIXEL_THOLD', 0.1),
            'IMAGE_FILE_TYPE'                : self.indi_allsky_config.get('IMAGE_FILE_TYPE', 'jpg'),
            'IMAGE_FILE_COMPRESSION__JPG'    : self.indi_allsky_config.get('IMAGE_FILE_COMPRESSION', {}).get('jpg', 90),
            'IMAGE_FILE_COMPRESSION__PNG'    : self.indi_allsky_config.get('IMAGE_FILE_COMPRESSION', {}).get('png', 5),
            'IMAGE_FILE_COMPRESSION__TIF'    : self.indi_allsky_config.get('IMAGE_FILE_COMPRESSION', {}).get('tif', 5),
            'IMAGE_FOLDER'                   : self.indi_allsky_config.get('IMAGE_FOLDER', '/var/www/html/allsky/images'),
            'IMAGE_EXTRA_TEXT'               : self.indi_allsky_config.get('IMAGE_EXTRA_TEXT', ''),
            'IMAGE_FLIP_V'                   : self.indi_allsky_config.get('IMAGE_FLIP_V', True),
            'IMAGE_FLIP_H'                   : self.indi_allsky_config.get('IMAGE_FLIP_H', True),
            'IMAGE_SCALE'                    : self.indi_allsky_config.get('IMAGE_SCALE', 100),
            'IMAGE_SAVE_FITS'                : self.indi_allsky_config.get('IMAGE_SAVE_FITS', False),
            'NIGHT_GRAYSCALE'                : self.indi_allsky_config.get('NIGHT_GRAYSCALE', False),
            'DAYTIME_GRAYSCALE'              : self.indi_allsky_config.get('DAYTIME_GRAYSCALE', False),
            'IMAGE_EXPORT_RAW'               : self.indi_allsky_config.get('IMAGE_EXPORT_RAW', ''),
            'IMAGE_EXPORT_FOLDER'            : self.indi_allsky_config.get('IMAGE_EXPORT_FOLDER', '/var/www/html/allsky/images/export'),
            'IMAGE_EXPIRE_DAYS'              : self.indi_allsky_config.get('IMAGE_EXPIRE_DAYS', 30),
            'FFMPEG_FRAMERATE'               : self.indi_allsky_config.get('FFMPEG_FRAMERATE', 25),
            'FFMPEG_BITRATE'                 : self.indi_allsky_config.get('FFMPEG_BITRATE', '2500k'),
            'TEXT_PROPERTIES__FONT_FACE'     : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_FACE', 'FONT_HERSHEY_SIMPLEX'),
            'TEXT_PROPERTIES__FONT_HEIGHT'   : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_HEIGHT', 30),
            'TEXT_PROPERTIES__FONT_X'        : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_X', 15),
            'TEXT_PROPERTIES__FONT_Y'        : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_Y', 30),
            'TEXT_PROPERTIES__FONT_SCALE'    : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_SCALE', 0.8),
            'TEXT_PROPERTIES__FONT_THICKNESS': self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_THICKNESS', 1),
            'TEXT_PROPERTIES__FONT_OUTLINE'  : self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_OUTLINE', True),
            'ORB_PROPERTIES__RADIUS'         : self.indi_allsky_config.get('ORB_PROPERTIES', {}).get('RADIUS', 9),
            'FILETRANSFER__CLASSNAME'        : self.indi_allsky_config.get('FILETRANSFER', {}).get('CLASSNAME', 'pycurl_sftp'),
            'FILETRANSFER__HOST'             : self.indi_allsky_config.get('FILETRANSFER', {}).get('HOST', ''),
            'FILETRANSFER__PORT'             : self.indi_allsky_config.get('FILETRANSFER', {}).get('PORT', 0),
            'FILETRANSFER__USERNAME'         : self.indi_allsky_config.get('FILETRANSFER', {}).get('USERNAME', ''),
            'FILETRANSFER__PASSWORD'         : self.indi_allsky_config.get('FILETRANSFER', {}).get('PASSWORD', ''),
            'FILETRANSFER__TIMEOUT'          : self.indi_allsky_config.get('FILETRANSFER', {}).get('TIMEOUT', 5.0),
            'FILETRANSFER__REMOTE_IMAGE_NAME'         : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_IMAGE_NAME', 'image.{0}'),
            'FILETRANSFER__REMOTE_IMAGE_FOLDER'       : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_IMAGE_FOLDER', '/tmp'),
            'FILETRANSFER__REMOTE_VIDEO_FOLDER'       : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_VIDEO_FOLDER', '/tmp'),
            'FILETRANSFER__REMOTE_KEOGRAM_FOLDER'     : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_KEOGRAM_FOLDER', '/tmp'),
            'FILETRANSFER__REMOTE_STARTRAIL_FOLDER'   : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_STARTRAIL_FOLDER', '/tmp'),
            'FILETRANSFER__REMOTE_ENDOFNIGHT_FOLDER'  : self.indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_ENDOFNIGHT_FOLDER', '/tmp'),
            'FILETRANSFER__UPLOAD_IMAGE'     : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE', 0),
            'FILETRANSFER__UPLOAD_VIDEO'     : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_VIDEO', False),
            'FILETRANSFER__UPLOAD_KEOGRAM'   : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_KEOGRAM', False),
            'FILETRANSFER__UPLOAD_STARTRAIL' : self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_STARTRAIL', False),
            'FILETRANSFER__UPLOAD_ENDOFNIGHT': self.indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_ENDOFNIGHT', False),
            'MQTTPUBLISH__ENABLE'            : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('ENABLE', False),
            'MQTTPUBLISH__TRANSPORT'         : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('TRANSPORT', 'tcp'),
            'MQTTPUBLISH__HOST'              : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('HOST', 'localhost'),
            'MQTTPUBLISH__PORT'              : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('PORT', 8883),
            'MQTTPUBLISH__USERNAME'          : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('USERNAME', 'indi-allsky'),
            'MQTTPUBLISH__PASSWORD'          : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('PASSWORD', ''),
            'MQTTPUBLISH__BASE_TOPIC'        : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('BASE_TOPIC', 'indi-allsky'),
            'MQTTPUBLISH__QOS'               : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('QOS', 0),
            'MQTTPUBLISH__TLS'               : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('TLS', True),
            'MQTTPUBLISH__CERT_BYPASS'       : self.indi_allsky_config.get('MQTTPUBLISH', {}).get('CERT_BYPASS', True),
        }


        # ADU_ROI
        ADU_ROI = self.indi_allsky_config.get('ADU_ROI', [])
        if ADU_ROI is None:
            ADU_ROI = []
        elif isinstance(ADU_ROI, bool):
            ADU_ROI = []

        try:
            form_data['ADU_ROI_X1'] = ADU_ROI[0]
        except IndexError:
            form_data['ADU_ROI_X1'] = 0

        try:
            form_data['ADU_ROI_Y1'] = ADU_ROI[1]
        except IndexError:
            form_data['ADU_ROI_Y1'] = 0

        try:
            form_data['ADU_ROI_X2'] = ADU_ROI[2]
        except IndexError:
            form_data['ADU_ROI_X2'] = 0

        try:
            form_data['ADU_ROI_Y2'] = ADU_ROI[3]
        except IndexError:
            form_data['ADU_ROI_Y2'] = 0


        # SQM_ROI
        SQM_ROI = self.indi_allsky_config.get('SQM_ROI', [])
        if SQM_ROI is None:
            SQM_ROI = []
        elif isinstance(SQM_ROI, bool):
            SQM_ROI = []

        try:
            form_data['SQM_ROI_X1'] = SQM_ROI[0]
        except IndexError:
            form_data['SQM_ROI_X1'] = 0

        try:
            form_data['SQM_ROI_Y1'] = SQM_ROI[1]
        except IndexError:
            form_data['SQM_ROI_Y1'] = 0

        try:
            form_data['SQM_ROI_X2'] = SQM_ROI[2]
        except IndexError:
            form_data['SQM_ROI_X2'] = 0

        try:
            form_data['SQM_ROI_Y2'] = SQM_ROI[3]
        except IndexError:
            form_data['SQM_ROI_Y2'] = 0


        # IMAGE_CROP_ROI
        IMAGE_CROP_ROI = self.indi_allsky_config.get('IMAGE_CROP_ROI', [])
        if IMAGE_CROP_ROI is None:
            IMAGE_CROP_ROI = []
        elif isinstance(IMAGE_CROP_ROI, bool):
            IMAGE_CROP_ROI = []

        try:
            form_data['IMAGE_CROP_ROI_X1'] = IMAGE_CROP_ROI[0]
        except IndexError:
            form_data['IMAGE_CROP_ROI_X1'] = 0

        try:
            form_data['IMAGE_CROP_ROI_Y1'] = IMAGE_CROP_ROI[1]
        except IndexError:
            form_data['IMAGE_CROP_ROI_Y1'] = 0

        try:
            form_data['IMAGE_CROP_ROI_X2'] = IMAGE_CROP_ROI[2]
        except IndexError:
            form_data['IMAGE_CROP_ROI_X2'] = 0

        try:
            form_data['IMAGE_CROP_ROI_Y2'] = IMAGE_CROP_ROI[3]
        except IndexError:
            form_data['IMAGE_CROP_ROI_Y2'] = 0



        # Font color
        text_properties__font_color = self.indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_COLOR', [200, 200, 200])
        text_properties__font_color_str = [str(x) for x in text_properties__font_color]
        form_data['TEXT_PROPERTIES__FONT_COLOR'] = ','.join(text_properties__font_color_str)

        # Sun orb color
        orb_properties__sun_color = self.indi_allsky_config.get('ORB_PROPERTIES', {}).get('SUN_COLOR', [255, 255, 255])
        orb_properties__sun_color_str = [str(x) for x in orb_properties__sun_color]
        form_data['ORB_PROPERTIES__SUN_COLOR'] = ','.join(orb_properties__sun_color_str)

        # Moon orb color
        orb_properties__moon_color = self.indi_allsky_config.get('ORB_PROPERTIES', {}).get('MOON_COLOR', [128, 128, 128])
        orb_properties__moon_color_str = [str(x) for x in orb_properties__moon_color]
        form_data['ORB_PROPERTIES__MOON_COLOR'] = ','.join(orb_properties__moon_color_str)


        # INDI config as json text
        indi_config_defaults = self.indi_allsky_config.get('INDI_CONFIG_DEFAULTS', {})
        form_data['INDI_CONFIG_DEFAULTS'] = json.dumps(indi_config_defaults, indent=4)

        context['form_config'] = IndiAllskyConfigForm(data=form_data)

        return context


class AjaxConfigView(BaseView):
    methods = ['POST']

    def dispatch_request(self):
        form_config = IndiAllskyConfigForm(data=request.json)

        if not form_config.validate():
            form_errors = form_config.errors  # this must be a property
            form_errors['form_global'] = ['Please fix the errors above']
            return jsonify(form_errors), 400


        # form passed validation

        if not self.indi_allsky_config:
            return jsonify({}), 400


        # sanity check
        if not self.indi_allsky_config.get('CCD_CONFIG'):
            self.indi_allsky_config['CCD_CONFIG'] = {}

        if not self.indi_allsky_config['CCD_CONFIG'].get('NIGHT'):
            self.indi_allsky_config['CCD_CONFIG']['NIGHT'] = {}

        if not self.indi_allsky_config['CCD_CONFIG'].get('MOONMODE'):
            self.indi_allsky_config['CCD_CONFIG']['MOONMODE'] = {}

        if not self.indi_allsky_config['CCD_CONFIG'].get('DAY'):
            self.indi_allsky_config['CCD_CONFIG']['DAY'] = {}

        if not self.indi_allsky_config.get('IMAGE_FILE_COMPRESSION'):
            self.indi_allsky_config['IMAGE_FILE_COMPRESSION'] = {}

        if not self.indi_allsky_config.get('TEXT_PROPERTIES'):
            self.indi_allsky_config['TEXT_PROPERTIES'] = {}

        if not self.indi_allsky_config.get('ORB_PROPERTIES'):
            self.indi_allsky_config['ORB_PROPERTIES'] = {}

        if not self.indi_allsky_config.get('FILETRANSFER'):
            self.indi_allsky_config['FILETRANSFER'] = {}

        if not self.indi_allsky_config.get('MQTTPUBLISH'):
            self.indi_allsky_config['MQTTPUBLISH'] = {}


        # update data
        self.indi_allsky_config['INDI_SERVER']                          = str(request.json['INDI_SERVER'])
        self.indi_allsky_config['INDI_PORT']                            = int(request.json['INDI_PORT'])
        self.indi_allsky_config['CCD_CONFIG']['NIGHT']['GAIN']          = int(request.json['CCD_CONFIG__NIGHT__GAIN'])
        self.indi_allsky_config['CCD_CONFIG']['NIGHT']['BINNING']       = int(request.json['CCD_CONFIG__NIGHT__BINNING'])
        self.indi_allsky_config['CCD_CONFIG']['MOONMODE']['GAIN']       = int(request.json['CCD_CONFIG__MOONMODE__GAIN'])
        self.indi_allsky_config['CCD_CONFIG']['MOONMODE']['BINNING']    = int(request.json['CCD_CONFIG__MOONMODE__BINNING'])
        self.indi_allsky_config['CCD_CONFIG']['DAY']['GAIN']            = int(request.json['CCD_CONFIG__DAY__GAIN'])
        self.indi_allsky_config['CCD_CONFIG']['DAY']['BINNING']         = int(request.json['CCD_CONFIG__DAY__BINNING'])
        self.indi_allsky_config['CCD_EXPOSURE_MAX']                     = float(request.json['CCD_EXPOSURE_MAX'])
        self.indi_allsky_config['CCD_EXPOSURE_DEF']                     = float(request.json['CCD_EXPOSURE_DEF'])
        self.indi_allsky_config['CCD_EXPOSURE_MIN']                     = float(request.json['CCD_EXPOSURE_MIN'])
        self.indi_allsky_config['EXPOSURE_PERIOD']                      = float(request.json['EXPOSURE_PERIOD'])
        self.indi_allsky_config['AUTO_WB']                              = bool(request.json['AUTO_WB'])
        self.indi_allsky_config['TEMP_DISPLAY']                         = str(request.json['TEMP_DISPLAY'])
        self.indi_allsky_config['TARGET_ADU']                           = int(request.json['TARGET_ADU'])
        self.indi_allsky_config['TARGET_ADU_DEV']                       = int(request.json['TARGET_ADU_DEV'])
        self.indi_allsky_config['DETECT_STARS']                         = bool(request.json['DETECT_STARS'])
        self.indi_allsky_config['LOCATION_LATITUDE']                    = float(request.json['LOCATION_LATITUDE'])
        self.indi_allsky_config['LOCATION_LONGITUDE']                   = float(request.json['LOCATION_LONGITUDE'])
        self.indi_allsky_config['TIMELAPSE_ENABLE']                     = bool(request.json['TIMELAPSE_ENABLE'])
        self.indi_allsky_config['DAYTIME_CAPTURE']                      = bool(request.json['DAYTIME_CAPTURE'])
        self.indi_allsky_config['DAYTIME_TIMELAPSE']                    = bool(request.json['DAYTIME_TIMELAPSE'])
        self.indi_allsky_config['DAYTIME_CONTRAST_ENHANCE']             = bool(request.json['DAYTIME_CONTRAST_ENHANCE'])
        self.indi_allsky_config['NIGHT_CONTRAST_ENHANCE']               = bool(request.json['NIGHT_CONTRAST_ENHANCE'])
        self.indi_allsky_config['NIGHT_SUN_ALT_DEG']                    = float(request.json['NIGHT_SUN_ALT_DEG'])
        self.indi_allsky_config['NIGHT_MOONMODE_ALT_DEG']               = float(request.json['NIGHT_MOONMODE_ALT_DEG'])
        self.indi_allsky_config['NIGHT_MOONMODE_PHASE']                 = float(request.json['NIGHT_MOONMODE_PHASE'])
        self.indi_allsky_config['KEOGRAM_ANGLE']                        = float(request.json['KEOGRAM_ANGLE'])
        self.indi_allsky_config['KEOGRAM_H_SCALE']                      = int(request.json['KEOGRAM_H_SCALE'])
        self.indi_allsky_config['KEOGRAM_V_SCALE']                      = int(request.json['KEOGRAM_V_SCALE'])
        self.indi_allsky_config['KEOGRAM_LABEL']                        = bool(request.json['KEOGRAM_LABEL'])
        self.indi_allsky_config['STARTRAILS_MAX_ADU']                   = int(request.json['STARTRAILS_MAX_ADU'])
        self.indi_allsky_config['STARTRAILS_MASK_THOLD']                = int(request.json['STARTRAILS_MASK_THOLD'])
        self.indi_allsky_config['STARTRAILS_PIXEL_THOLD']               = float(request.json['STARTRAILS_PIXEL_THOLD'])
        self.indi_allsky_config['IMAGE_FILE_TYPE']                      = str(request.json['IMAGE_FILE_TYPE'])
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['jpg']        = int(request.json['IMAGE_FILE_COMPRESSION__JPG'])
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['jpeg']       = int(request.json['IMAGE_FILE_COMPRESSION__JPG'])  # duplicate
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['png']        = int(request.json['IMAGE_FILE_COMPRESSION__PNG'])
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['tif']        = int(request.json['IMAGE_FILE_COMPRESSION__TIF'])
        self.indi_allsky_config['IMAGE_FILE_COMPRESSION']['tiff']       = int(request.json['IMAGE_FILE_COMPRESSION__TIF'])  # duplicate
        self.indi_allsky_config['IMAGE_FOLDER']                         = str(request.json['IMAGE_FOLDER'])
        self.indi_allsky_config['IMAGE_EXTRA_TEXT']                     = str(request.json['IMAGE_EXTRA_TEXT'])
        self.indi_allsky_config['IMAGE_FLIP_V']                         = bool(request.json['IMAGE_FLIP_V'])
        self.indi_allsky_config['IMAGE_FLIP_H']                         = bool(request.json['IMAGE_FLIP_H'])
        self.indi_allsky_config['IMAGE_SCALE']                          = int(request.json['IMAGE_SCALE'])
        self.indi_allsky_config['IMAGE_SAVE_FITS']                      = bool(request.json['IMAGE_SAVE_FITS'])
        self.indi_allsky_config['NIGHT_GRAYSCALE']                      = bool(request.json['NIGHT_GRAYSCALE'])
        self.indi_allsky_config['DAYTIME_GRAYSCALE']                    = bool(request.json['DAYTIME_GRAYSCALE'])
        self.indi_allsky_config['IMAGE_EXPORT_RAW']                     = str(request.json['IMAGE_EXPORT_RAW'])
        self.indi_allsky_config['IMAGE_EXPORT_FOLDER']                  = str(request.json['IMAGE_EXPORT_FOLDER'])
        self.indi_allsky_config['IMAGE_EXPIRE_DAYS']                    = int(request.json['IMAGE_EXPIRE_DAYS'])
        self.indi_allsky_config['FFMPEG_FRAMERATE']                     = int(request.json['FFMPEG_FRAMERATE'])
        self.indi_allsky_config['FFMPEG_BITRATE']                       = str(request.json['FFMPEG_BITRATE'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_FACE']         = str(request.json['TEXT_PROPERTIES__FONT_FACE'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_HEIGHT']       = int(request.json['TEXT_PROPERTIES__FONT_HEIGHT'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_X']            = int(request.json['TEXT_PROPERTIES__FONT_X'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_Y']            = int(request.json['TEXT_PROPERTIES__FONT_Y'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_SCALE']        = float(request.json['TEXT_PROPERTIES__FONT_SCALE'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_THICKNESS']    = int(request.json['TEXT_PROPERTIES__FONT_THICKNESS'])
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_OUTLINE']      = bool(request.json['TEXT_PROPERTIES__FONT_OUTLINE'])
        self.indi_allsky_config['ORB_PROPERTIES']['RADIUS']             = int(request.json['ORB_PROPERTIES__RADIUS'])
        self.indi_allsky_config['FILETRANSFER']['CLASSNAME']            = str(request.json['FILETRANSFER__CLASSNAME'])
        self.indi_allsky_config['FILETRANSFER']['HOST']                 = str(request.json['FILETRANSFER__HOST'])
        self.indi_allsky_config['FILETRANSFER']['PORT']                 = int(request.json['FILETRANSFER__PORT'])
        self.indi_allsky_config['FILETRANSFER']['USERNAME']             = str(request.json['FILETRANSFER__USERNAME'])
        self.indi_allsky_config['FILETRANSFER']['PASSWORD']             = str(request.json['FILETRANSFER__PASSWORD'])
        self.indi_allsky_config['FILETRANSFER']['TIMEOUT']              = float(request.json['FILETRANSFER__TIMEOUT'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_IMAGE_NAME']        = str(request.json['FILETRANSFER__REMOTE_IMAGE_NAME'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_IMAGE_FOLDER']      = str(request.json['FILETRANSFER__REMOTE_IMAGE_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_VIDEO_FOLDER']      = str(request.json['FILETRANSFER__REMOTE_VIDEO_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_KEOGRAM_FOLDER']    = str(request.json['FILETRANSFER__REMOTE_KEOGRAM_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_STARTRAIL_FOLDER']  = str(request.json['FILETRANSFER__REMOTE_STARTRAIL_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['REMOTE_ENDOFNIGHT_FOLDER'] = str(request.json['FILETRANSFER__REMOTE_ENDOFNIGHT_FOLDER'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_IMAGE']         = int(request.json['FILETRANSFER__UPLOAD_IMAGE'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_VIDEO']         = bool(request.json['FILETRANSFER__UPLOAD_VIDEO'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_KEOGRAM']       = bool(request.json['FILETRANSFER__UPLOAD_KEOGRAM'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_STARTRAIL']     = bool(request.json['FILETRANSFER__UPLOAD_STARTRAIL'])
        self.indi_allsky_config['FILETRANSFER']['UPLOAD_ENDOFNIGHT']    = bool(request.json['FILETRANSFER__UPLOAD_ENDOFNIGHT'])
        self.indi_allsky_config['MQTTPUBLISH']['ENABLE']                = bool(request.json['MQTTPUBLISH__ENABLE'])
        self.indi_allsky_config['MQTTPUBLISH']['TRANSPORT']             = str(request.json['MQTTPUBLISH__TRANSPORT'])
        self.indi_allsky_config['MQTTPUBLISH']['HOST']                  = str(request.json['MQTTPUBLISH__HOST'])
        self.indi_allsky_config['MQTTPUBLISH']['PORT']                  = int(request.json['MQTTPUBLISH__PORT'])
        self.indi_allsky_config['MQTTPUBLISH']['USERNAME']              = str(request.json['MQTTPUBLISH__USERNAME'])
        self.indi_allsky_config['MQTTPUBLISH']['PASSWORD']              = str(request.json['MQTTPUBLISH__PASSWORD'])
        self.indi_allsky_config['MQTTPUBLISH']['BASE_TOPIC']            = str(request.json['MQTTPUBLISH__BASE_TOPIC'])
        self.indi_allsky_config['MQTTPUBLISH']['QOS']                   = int(request.json['MQTTPUBLISH__QOS'])
        self.indi_allsky_config['MQTTPUBLISH']['TLS']                   = bool(request.json['MQTTPUBLISH__TLS'])
        self.indi_allsky_config['MQTTPUBLISH']['CERT_BYPASS']           = bool(request.json['MQTTPUBLISH__CERT_BYPASS'])

        self.indi_allsky_config['INDI_CONFIG_DEFAULTS']                 = json.loads(str(request.json['INDI_CONFIG_DEFAULTS']))


        # ADU_ROI
        adu_roi_x1 = int(request.json['ADU_ROI_X1'])
        adu_roi_y1 = int(request.json['ADU_ROI_Y1'])
        adu_roi_x2 = int(request.json['ADU_ROI_X2'])
        adu_roi_y2 = int(request.json['ADU_ROI_Y2'])

        # the x2 and y2 values must be positive integers in order to be enabled and valid
        if adu_roi_x2 and adu_roi_y2:
            self.indi_allsky_config['ADU_ROI'] = [adu_roi_x1, adu_roi_y1, adu_roi_x2, adu_roi_y2]
        else:
            self.indi_allsky_config['ADU_ROI'] = []


        # SQM_ROI
        sqm_roi_x1 = int(request.json['SQM_ROI_X1'])
        sqm_roi_y1 = int(request.json['SQM_ROI_Y1'])
        sqm_roi_x2 = int(request.json['SQM_ROI_X2'])
        sqm_roi_y2 = int(request.json['SQM_ROI_Y2'])

        # the x2 and y2 values must be positive integers in order to be enabled and valid
        if sqm_roi_x2 and sqm_roi_y2:
            self.indi_allsky_config['SQM_ROI'] = [sqm_roi_x1, sqm_roi_y1, sqm_roi_x2, sqm_roi_y2]
        else:
            self.indi_allsky_config['SQM_ROI'] = []


        # IMAGE_CROP_ROI
        image_crop_roi_x1 = int(request.json['IMAGE_CROP_ROI_X1'])
        image_crop_roi_y1 = int(request.json['IMAGE_CROP_ROI_Y1'])
        image_crop_roi_x2 = int(request.json['IMAGE_CROP_ROI_X2'])
        image_crop_roi_y2 = int(request.json['IMAGE_CROP_ROI_Y2'])

        # the x2 and y2 values must be positive integers in order to be enabled and valid
        if image_crop_roi_x2 and image_crop_roi_y2:
            self.indi_allsky_config['IMAGE_CROP_ROI'] = [image_crop_roi_x1, image_crop_roi_y1, image_crop_roi_x2, image_crop_roi_y2]
        else:
            self.indi_allsky_config['IMAGE_CROP_ROI'] = []



        # TEXT_PROPERTIES FONT_COLOR
        font_color_str = str(request.json['TEXT_PROPERTIES__FONT_COLOR'])
        font_r, font_g, font_b = font_color_str.split(',')
        self.indi_allsky_config['TEXT_PROPERTIES']['FONT_COLOR'] = [int(font_r), int(font_g), int(font_b)]

        # ORB_PROPERTIES SUN_COLOR
        sun_color_str = str(request.json['ORB_PROPERTIES__SUN_COLOR'])
        sun_r, sun_g, sun_b = sun_color_str.split(',')
        self.indi_allsky_config['ORB_PROPERTIES']['SUN_COLOR'] = [int(sun_r), int(sun_g), int(sun_b)]

        # ORB_PROPERTIES MOON_COLOR
        moon_color_str = str(request.json['ORB_PROPERTIES__MOON_COLOR'])
        moon_r, moon_g, moon_b = moon_color_str.split(',')
        self.indi_allsky_config['ORB_PROPERTIES']['MOON_COLOR'] = [int(moon_r), int(moon_g), int(moon_b)]


        # save new config
        try:
            with io.open(app.config['INDI_ALLSKY_CONFIG'], 'w') as f_config_file:
                f_config_file.write(json.dumps(self.indi_allsky_config, indent=4))
                f_config_file.flush()

            app.logger.info('Wrote new config.json')
        except PermissionError as e:
            app.logger.error('PermissionError: %s', str(e))
            error_data = {
                'form_global' : [str(e)],
            }
            return jsonify(error_data), 400


        message = {
            'success-message' : 'Wrote new config',
        }

        return jsonify(message)


class ImageViewerView(FormView):
    def get_context(self):
        context = super(ImageViewerView, self).get_context()

        form_data = {
            'YEAR_SELECT'  : None,
            'MONTH_SELECT' : None,
            'DAY_SELECT'   : None,
            'HOUR_SELECT'  : None,
        }

        context['form_viewer'] = IndiAllskyImageViewerPreload(data=form_data)

        return context



class AjaxImageViewerView(BaseView):
    methods = ['POST']

    def __init__(self):
        self.camera_id = self.getLatestCamera()


    def dispatch_request(self):
        form_viewer = IndiAllskyImageViewer(data=request.json)


        form_year  = request.json.get('YEAR_SELECT')
        form_month = request.json.get('MONTH_SELECT')
        form_day   = request.json.get('DAY_SELECT')
        form_hour  = request.json.get('HOUR_SELECT')

        json_data = {}


        if form_hour:
            form_datetime = datetime.strptime('{0} {1} {2} {3}'.format(form_year, form_month, form_day, form_hour), '%Y %m %d %H')

            year = form_datetime.strftime('%Y')
            month = form_datetime.strftime('%m')
            day = form_datetime.strftime('%d')
            hour = form_datetime.strftime('%H')

            json_data['IMG_SELECT'] = form_viewer.getImages(year, month, day, hour)


        elif form_day:
            form_datetime = datetime.strptime('{0} {1} {2}'.format(form_year, form_month, form_day), '%Y %m %d')

            year = form_datetime.strftime('%Y')
            month = form_datetime.strftime('%m')
            day = form_datetime.strftime('%d')

            json_data['HOUR_SELECT'] = form_viewer.getHours(year, month, day)
            hour = json_data['HOUR_SELECT'][0][0]

            json_data['IMG_SELECT'] = form_viewer.getImages(year, month, day, hour)

        elif form_month:
            form_datetime = datetime.strptime('{0} {1}'.format(form_year, form_month), '%Y %m')

            year = form_datetime.strftime('%Y')
            month = form_datetime.strftime('%m')

            json_data['DAY_SELECT'] = form_viewer.getDays(year, month)
            day = json_data['DAY_SELECT'][0][0]

            json_data['HOUR_SELECT'] = form_viewer.getHours(year, month, day)
            hour = json_data['HOUR_SELECT'][0][0]

            json_data['IMG_SELECT'] = form_viewer.getImages(year, month, day, hour)

        elif form_year:
            form_datetime = datetime.strptime('{0}'.format(form_year), '%Y')

            year = form_datetime.strftime('%Y')

            json_data['MONTH_SELECT'] = form_viewer.getMonths(year)
            month = json_data['MONTH_SELECT'][0][0]

            json_data['DAY_SELECT'] = form_viewer.getDays(year, month)
            day = json_data['DAY_SELECT'][0][0]

            json_data['HOUR_SELECT'] = form_viewer.getHours(year, month, day)
            hour = json_data['HOUR_SELECT'][0][0]

            json_data['IMG_SELECT'] = form_viewer.getImages(year, month, day, hour)

        return jsonify(json_data)


class VideoViewerView(FormView):
    def get_context(self):
        context = super(VideoViewerView, self).get_context()

        form_data = {
            'YEAR_SELECT'  : None,
            'MONTH_SELECT' : None,
        }

        context['form_video_viewer'] = IndiAllskyVideoViewerPreload(data=form_data)

        return context


class AjaxVideoViewerView(BaseView):
    methods = ['POST']

    def __init__(self):
        self.camera_id = self.getLatestCamera()


    def dispatch_request(self):
        form_video_viewer = IndiAllskyVideoViewer(data=request.json)


        form_year      = request.json.get('YEAR_SELECT')
        form_month     = request.json.get('MONTH_SELECT')
        form_timeofday = request.json.get('TIMEOFDAY_SELECT')

        json_data = {}

        if form_month:
            form_datetime = datetime.strptime('{0} {1}'.format(form_year, form_month), '%Y %m')

            year = form_datetime.strftime('%Y')
            month = form_datetime.strftime('%m')

            json_data['video_list'] = form_video_viewer.getVideos(year, month, form_timeofday)

        elif form_year:
            form_datetime = datetime.strptime('{0}'.format(form_year), '%Y')

            year = form_datetime.strftime('%Y')

            json_data['MONTH_SELECT'] = form_video_viewer.getMonths(year)
            month = json_data['MONTH_SELECT'][0][0]

            json_data['video_list'] = form_video_viewer.getVideos(year, month, form_timeofday)

        return jsonify(json_data)


class SystemInfoView(TemplateView):
    def get_context(self):
        context = super(SystemInfoView, self).get_context()

        context['uptime_str'] = self.getUptime()

        context['cpu_count'] = self.getCpuCount()
        context['cpu_usage'] = self.getCpuUsage()

        load5, load10, load15 = self.getLoadAverage()
        context['cpu_load5'] = load5
        context['cpu_load10'] = load10
        context['cpu_load15'] = load15

        mem_total, mem_usage = self.getMemoryUsage()
        context['mem_total'] = mem_total
        context['mem_usage'] = mem_usage

        context['swap_usage'] = self.getSwapUsage()

        context['fs_data'] = self.getAllFsUsage()

        context['temp_list'] = self.getTemps()

        context['net_list'] = self.getNetworkIps()

        context['indiserver_service'] = self.getSystemdUnitStatus(app.config['INDISEVER_SERVICE_NAME'])
        context['indi_allsky_service'] = self.getSystemdUnitStatus(app.config['ALLSKY_SERVICE_NAME'])
        context['gunicorn_indi_allsky_service'] = self.getSystemdUnitStatus(app.config['GUNICORN_SERVICE_NAME'])

        context['python_version'] = platform.python_version()
        context['python_platform'] = platform.machine()

        context['cv2_version'] = str(getattr(cv2, '__version__', -1))
        context['ephem_version'] = str(getattr(ephem, '__version__', -1))
        context['numpy_version'] = str(getattr(numpy, '__version__', -1))
        context['astropy_version'] = str(getattr(astropy, '__version__', -1))
        context['flask_version'] = str(getattr(flask, '__version__', -1))
        context['dbus_version'] = str(getattr(dbus, '__version__', -1))
        context['paramiko_version'] = str(getattr(paramiko, '__version__', -1))
        context['pycurl_version'] = str(getattr(pycurl, 'version', -1))
        context['pahomqtt_version'] = str(getattr(paho.mqtt, '__version__', -1))
        context['ccdproc_version'] = str(getattr(ccdproc, '__version__', -1))
        context['pyindi_version'] = '.'.join((
            str(getattr(PyIndi, 'INDI_VERSION_MAJOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_MINOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_RELEASE', -1)),
        ))

        return context


    def getUptime(self):
        uptime_s = time.time() - psutil.boot_time()

        days = int(uptime_s / 86400)
        uptime_s -= (days * 86400)

        hours = int(uptime_s / 3600)
        uptime_s -= (hours * 3600)

        minutes = int(uptime_s / 60)
        uptime_s -= (minutes * 60)

        seconds = int(uptime_s)

        uptime_str = '{0:d} days, {1:d} hours, {2:d} minutes, {3:d} seconds'.format(days, hours, minutes, seconds)

        return uptime_str


    def getCpuCount(self):
        return psutil.cpu_count()


    def getCpuUsage(self):
        return psutil.cpu_percent()


    def getLoadAverage(self):
        return psutil.getloadavg()


    def getMemoryUsage(self):
        memory_info = psutil.virtual_memory()

        memory_total = memory_info[0]
        #memory_free = memory_info[1]
        memory_percent = memory_info[2]

        memory_total_mb = int(memory_total / 1024.0 / 1024.0)

        #memory_percent = 100 - ((memory_free * 100) / memory_total)

        return memory_total_mb, memory_percent


    def getSwapUsage(self):
        swap_info = psutil.swap_memory()

        return swap_info[3]


    def getAllFsUsage(self):
        fs_list = psutil.disk_partitions()

        fs_data = list()
        for fs in fs_list:
            disk_usage = psutil.disk_usage(fs.mountpoint)

            data = {
                'total_gb'   : disk_usage.total / 1024.0 / 1024.0 / 1024.0,
                'mountpoint' : fs.mountpoint,
                'percent'    : disk_usage.percent,
            }

            fs_data.append(data)

        return fs_data


    def getTemps(self):
        temp_info = psutil.sensors_temperatures()

        temp_list = list()
        for t_key in temp_info.keys():
            for i in temp_info[t_key]:
                if self.indi_allsky_config.get('TEMP_DISPLAY') == 'f':
                    current_temp = ((i.current * 9.0 ) / 5.0) + 32
                    temp_sys = 'F'
                elif self.indi_allsky_config.get('TEMP_DISPLAY') == 'k':
                    current_temp = i.current + 273.15
                    temp_sys = 'K'
                else:
                    current_temp = float(i.current)
                    temp_sys = 'C'

                temp_list.append({
                    'name' : t_key,
                    'temp' : current_temp,
                    'sys'  : temp_sys,
                })

        return temp_list


    def getNetworkIps(self):
        net_info = psutil.net_if_addrs()

        net_list = list()
        for dev, addr_info in net_info.items():
            if dev == 'lo':
                # skip loopback
                continue


            dev_info = {
                'name'  : dev,
                'inet4' : [],
                'inet6' : [],
            }

            for addr in addr_info:
                if addr.family == socket.AF_INET:
                    dev_info['inet4'].append(addr.address)

                elif addr.family == socket.AF_INET6:
                    dev_info['inet6'].append(addr.address)

            net_list.append(dev_info)


        return net_list


    def getSystemdUnitStatus(self, unit):
        session_bus = dbus.SessionBus()
        systemd1 = session_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')

        try:
            service = session_bus.get_object('org.freedesktop.systemd1', object_path=manager.GetUnit(unit))
        except dbus.exceptions.DBusException:
            return 'UNKNOWN'

        interface = dbus.Interface(service, dbus_interface='org.freedesktop.DBus.Properties')
        unit_state = interface.Get('org.freedesktop.systemd1.Unit', 'ActiveState')

        return str(unit_state)



class TaskQueueView(TemplateView):
    def get_context(self):
        context = super(TaskQueueView, self).get_context()

        state_list = (
            TaskQueueState.MANUAL,
            TaskQueueState.QUEUED,
            TaskQueueState.RUNNING,
            TaskQueueState.SUCCESS,
            TaskQueueState.FAILED,
        )

        exclude_queues = (
            TaskQueueQueue.IMAGE,
            TaskQueueQueue.UPLOAD,
        )

        now_minus_1h = datetime.now() - timedelta(hours=1)

        tasks = IndiAllSkyDbTaskQueueTable.query\
            .filter(IndiAllSkyDbTaskQueueTable.createDate > now_minus_1h)\
            .filter(IndiAllSkyDbTaskQueueTable.state.in_(state_list))\
            .filter(~IndiAllSkyDbTaskQueueTable.queue.in_(exclude_queues))\
            .order_by(IndiAllSkyDbTaskQueueTable.createDate.asc())


        task_list = list()
        for task in tasks:
            t = {
                'id'         : task.id,
                'createDate' : task.createDate,
                'queue'      : task.queue.name,
                'state'      : task.state.name,
                'result'     : task.result,
            }

            task_list.append(t)

        context['task_list'] = task_list

        return context


class AjaxSystemInfoView(BaseView):
    methods = ['POST']

    def dispatch_request(self):
        form_system = IndiAllskySystemInfoForm(data=request.json)

        if not form_system.validate():
            form_errors = form_system.errors  # this must be a property
            return jsonify(form_errors), 400


        service = request.json['SERVICE_HIDDEN']
        command = request.json['COMMAND_HIDDEN']

        if service == app.config['INDISEVER_SERVICE_NAME']:
            if command == 'stop':
                r = self.stopSystemdUnit(app.config['INDISEVER_SERVICE_NAME'])
            elif command == 'start':
                r = self.startSystemdUnit(app.config['INDISEVER_SERVICE_NAME'])
            else:
                errors_data = {
                    'COMMAND_HIDDEN' : ['Unhandled command'],
                }
                return jsonify(errors_data), 400


        elif service == app.config['ALLSKY_SERVICE_NAME']:
            if command == 'hup':
                r = self.hupSystemdUnit(app.config['ALLSKY_SERVICE_NAME'])
            elif command == 'stop':
                r = self.stopSystemdUnit(app.config['ALLSKY_SERVICE_NAME'])
            elif command == 'start':
                r = self.startSystemdUnit(app.config['ALLSKY_SERVICE_NAME'])
            else:
                errors_data = {
                    'COMMAND_HIDDEN' : ['Unhandled command'],
                }
                return jsonify(errors_data), 400


        elif service == app.config['GUNICORN_SERVICE_NAME']:
            if command == 'stop':
                r = self.stopSystemdUnit(app.config['GUNICORN_SERVICE_NAME'])
            else:
                errors_data = {
                    'COMMAND_HIDDEN' : ['Unhandled command'],
                }
                return jsonify(errors_data), 400


        elif service == 'system':
            if command == 'reboot':
                r = self.rebootSystemd()
            elif command == 'poweroff':
                r = self.poweroffSystemd()
            else:
                errors_data = {
                    'COMMAND_HIDDEN' : ['Unhandled command'],
                }
                return jsonify(errors_data), 400


        else:
            errors_data = {
                'SERVICE_HIDDEN' : ['Unhandled service'],
            }
            return jsonify(errors_data), 400


        app.logger.info('Command return: %s', str(r))

        json_data = {
            'success-message' : 'Job submitted',
        }

        return jsonify(json_data)


    def stopSystemdUnit(self, unit):
        session_bus = dbus.SessionBus()
        systemd1 = session_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        r = manager.StopUnit(unit, 'fail')

        return r


    def startSystemdUnit(self, unit):
        session_bus = dbus.SessionBus()
        systemd1 = session_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        r = manager.StartUnit(unit, 'fail')

        return r


    def hupSystemdUnit(self, unit):
        session_bus = dbus.SessionBus()
        systemd1 = session_bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        r = manager.ReloadUnit(unit, 'fail')

        return r


    def rebootSystemd(self):
        system_bus = dbus.SystemBus()
        systemd1 = system_bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.login1.Manager')
        r = manager.Reboot(False)

        return r


    def poweroffSystemd(self):
        system_bus = dbus.SystemBus()
        systemd1 = system_bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.login1.Manager')
        r = manager.PowerOff(False)

        return r


# images are normally served directly by the web server, this is a backup method
@bp.route('/images/<path:path>')
def images_folder(path):
    app.logger.warning('Serving image file: %s', path)
    return send_from_directory(app.config['INDI_ALLSKY_IMAGE_FOLDER'], path)



bp.add_url_rule('/', view_func=IndexView.as_view('index_view', template_name='index.html'))
bp.add_url_rule('/imageviewer', view_func=ImageViewerView.as_view('imageviewer_view', template_name='imageviewer.html'))
bp.add_url_rule('/ajax/imageviewer', view_func=AjaxImageViewerView.as_view('ajax_imageviewer_view'))
bp.add_url_rule('/videoviewer', view_func=VideoViewerView.as_view('videoviewer_view', template_name='videoviewer.html'))
bp.add_url_rule('/ajax/videoviewer', view_func=AjaxVideoViewerView.as_view('ajax_videoviewer_view'))
bp.add_url_rule('/config', view_func=ConfigView.as_view('config_view', template_name='config.html'))
bp.add_url_rule('/ajax/config', view_func=AjaxConfigView.as_view('ajax_config_view'))
bp.add_url_rule('/sqm', view_func=SqmView.as_view('sqm_view', template_name='sqm.html'))
bp.add_url_rule('/loop', view_func=ImageLoopView.as_view('image_loop_view', template_name='loop.html'))
bp.add_url_rule('/js/loop', view_func=JsonImageLoopView.as_view('js_image_loop_view'))
bp.add_url_rule('/charts', view_func=ChartView.as_view('chart_view', template_name='chart.html'))
bp.add_url_rule('/js/charts', view_func=JsonChartView.as_view('js_chart_view'))
bp.add_url_rule('/system', view_func=SystemInfoView.as_view('system_view', template_name='system.html'))
bp.add_url_rule('/ajax/system', view_func=AjaxSystemInfoView.as_view('ajax_system_view'))
bp.add_url_rule('/tasks', view_func=TaskQueueView.as_view('taskqueue_view', template_name='taskqueue.html'))

# hidden
bp.add_url_rule('/cameras', view_func=CamerasView.as_view('cameras_view', template_name='cameras.html'))
bp.add_url_rule('/darks', view_func=DarkFramesView.as_view('darks_view', template_name='darks.html'))
bp.add_url_rule('/lag', view_func=ImageLagView.as_view('image_lag_view', template_name='lag.html'))

# work in progress
bp.add_url_rule('/viewer', view_func=ViewerView.as_view('viewer_view', template_name='viewer.html'))
