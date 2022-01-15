from datetime import datetime
from datetime import timedelta
import io
import json
from pathlib import Path
from collections import OrderedDict

from flask import render_template
from flask import request
from flask import jsonify
from flask import Blueprint
from flask.views import View

from flask import current_app as app  # noqa

from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable

from sqlalchemy import func
from sqlalchemy.types import DateTime

from .forms import IndiAllskyConfigForm

bp = Blueprint('indi-allsky', __name__, template_folder='templates', url_prefix='/')


#@bp.route('/')
#@bp.route('/index')
#def index():
#    return render_template('index.html')


class TemplateView(View):
    def __init__(self, template_name):
        self.template_name = template_name

    def dispatch_request(self):
        return render_template(self.template_name)


class ListView(View):
    def __init__(self, template_name):
        self.template_name = template_name

    def render_template(self, context):
        return render_template(self.template_name, **context)

    def dispatch_request(self):
        context = {'objects': self.get_objects()}
        return self.render_template(context)

    def get_objects(self):
        raise NotImplementedError()


class FormView(ListView):
    def dispatch_request(self):
        context = self.get_objects()
        return self.render_template(context)


class JsonView(View):
    def dispatch_request(self):
        json_data = self.get_objects()
        return jsonify(json_data)

    def get_objects(self):
        raise NotImplementedError()



class IndexView(TemplateView):
    pass


class CamerasView(ListView):
    def get_objects(self):
        cameras = IndiAllSkyDbCameraTable.query.all()
        return cameras


class SqmView(TemplateView):
    pass


class ImageLoopView(TemplateView):
    pass


class JsonImageLoopView(JsonView):
    def __init__(self):
        self.camera_id = self.getLatestCamera()
        self.limit = 40
        self.hours = 2
        self.sqm_history_minutes = 30
        self.stars_history_minutes = 30


    def get_objects(self):
        self.limit = request.args.get('limit', self.limit)

        data = {
            'image_list' : self.getLatestImages(),
            'sqm_data'   : self.getSqmData(),
            'stars_data' : self.getStarsData(),
        }

        return data


    def getLatestCamera(self):
        latest_camera = IndiAllSkyDbCameraTable.query\
            .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
            .first()

        return latest_camera.id


    def getLatestImages(self):
        now_minus_hours = datetime.now() - timedelta(hours=self.hours)

        createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        latest_images = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(createDate_local > now_minus_hours)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .limit(self.limit)

        image_list = list()
        for i in latest_images:
            filename_p = Path(i.filename)
            rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_DOCROOT'])

            data = {
                'file'  : str(rel_filename_p),
                'sqm'   : i.sqm,
                'stars' : i.stars,
            }

            image_list.append(data)

        return image_list


    def getSqmData(self):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.sqm_history_minutes)

        createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        sqm_images = db.session\
            .query(
                func.max(IndiAllSkyDbImageTable.sqm).label('image_max_sqm'),
                func.min(IndiAllSkyDbImageTable.sqm).label('image_min_sqm'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(createDate_local > now_minus_minutes)\
            .first()


        sqm_data = {
            'max' : sqm_images.image_max_sqm,
            'min' : sqm_images.image_min_sqm,
            'avg' : sqm_images.image_avg_sqm,
        }

        return sqm_data


    def getStarsData(self):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.stars_history_minutes)

        createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        stars_images = db.session\
            .query(
                func.max(IndiAllSkyDbImageTable.stars).label('image_max_stars'),
                func.min(IndiAllSkyDbImageTable.stars).label('image_min_stars'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(createDate_local > now_minus_minutes)\
            .first()


        stars_data = {
            'max' : stars_images.image_max_stars,
            'min' : stars_images.image_min_stars,
            'avg' : stars_images.image_avg_stars,
        }

        return stars_data


class ChartView(TemplateView):
    pass


class JsonChartView(JsonView):
    def __init__(self):
        self.camera_id = self.getLatestCamera()
        self.chart_history_minutes = 30


    def get_objects(self):
        data = {
            'chart_data' : self.getChartData(),
        }

        return data


    def getLatestCamera(self):
        latest_camera = IndiAllSkyDbCameraTable.query\
            .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
            .first()

        return latest_camera.id


    def getChartData(self):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.chart_history_minutes)

        createDate_local = func.datetime(IndiAllSkyDbImageTable.createDate, 'localtime', type_=DateTime).label('createDate_local')
        chart_query = db.session.query(
            createDate_local,
            IndiAllSkyDbImageTable.sqm,
            IndiAllSkyDbImageTable.stars,
        )\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(createDate_local > now_minus_minutes)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        #app.logger.info('Chart SQL: %s', str(chart_query))

        chart_data = {
            'sqm'   : [],
            'stars' : [],
        }
        for i in chart_query:
            sqm_data = {
                'x' : i.createDate_local.strftime('%H:%M:%S'),
                'y' : i.sqm,
            }
            chart_data['sqm'].append(sqm_data)

            star_data = {
                'x' : i.createDate_local.strftime('%H:%M:%S'),
                'y' : i.stars,
            }
            chart_data['stars'].append(star_data)


        return chart_data


class ConfigView(FormView):
    def get_objects(self):
        with io.open(app.config['INDI_ALLSKY_CONFIG'], 'r') as f_config_file:
            try:
                indi_allsky_config = json.loads(f_config_file.read())
            except json.JSONDecodeError as e:
                app.logger.error('Error decoding json: %s', str(e))


        form_data = {
            'CCD_CONFIG__NIGHT__GAIN'        : indi_allsky_config.get('CCD_CONFIG', {}).get('NIGHT', {}).get('GAIN', 0),
            'CCD_CONFIG__NIGHT__BINNING'     : indi_allsky_config.get('CCD_CONFIG', {}).get('NIGHT', {}).get('BINNING', 1),
            'CCD_CONFIG__MOONMODE__GAIN'     : indi_allsky_config.get('CCD_CONFIG', {}).get('MOONMODE', {}).get('GAIN', 0),
            'CCD_CONFIG__MOONMODE__BINNING'  : indi_allsky_config.get('CCD_CONFIG', {}).get('MOONMODE', {}).get('BINNING', 1),
            'CCD_CONFIG__DAY__GAIN'          : indi_allsky_config.get('CCD_CONFIG', {}).get('DAY', {}).get('GAIN', 0),
            'CCD_CONFIG__DAY__BINNING'       : indi_allsky_config.get('CCD_CONFIG', {}).get('DAY', {}).get('BINNING', 1),
            'CCD_EXPOSURE_MAX'               : indi_allsky_config.get('CCD_EXPOSURE_MAX', 15.0),
            'CCD_EXPOSURE_DEF'               : indi_allsky_config.get('CCD_EXPOSURE_DEF', 0.0),
            'CCD_EXPOSURE_MIN'               : indi_allsky_config.get('CCD_EXPOSURE_MIN', 0.0),
            'EXPOSURE_PERIOD'                : indi_allsky_config.get('CCD_EXPOSURE_PERIOD', 15.0),
            'AUTO_WB'                        : indi_allsky_config.get('AUTO_WB', True),
            'TARGET_ADU'                     : indi_allsky_config.get('TARGET_ADU', 75),
            'TARGET_ADU_DEV'                 : indi_allsky_config.get('TARGET_ADU_DEV', 10),
            'DETECT_STARS'                   : indi_allsky_config.get('DETECT_STARS', True),
            'LOCATION_LATITUDE'              : indi_allsky_config.get('LOCATION_LATITUDE', 0),
            'LOCATION_LONGITUDE'             : indi_allsky_config.get('LOCATION_LONGITUDE', 0),
            'DAYTIME_CAPTURE'                : indi_allsky_config.get('DAYTIME_CAPTURE', False),
            'DAYTIME_TIMELAPSE'              : indi_allsky_config.get('DAYTIME_TIMELAPSE', False),
            'DAYTIME_CONTRAST_ENHANCE'       : indi_allsky_config.get('DAYTIME_CONTRAST_ENHANCE', False),
            'NIGHT_CONTRAST_ENHANCE'         : indi_allsky_config.get('NIGHT_CONTRAST_ENHANCE', False),
            'NIGHT_SUN_ALT_DEG'              : indi_allsky_config.get('NIGHT_SUN_ALT_DEG', -6),
            'NIGHT_MOONMODE_ALT_DEG'         : indi_allsky_config.get('NIGHT_MOONMODE_ALT_DEG', 5),
            'NIGHT_MOONMODE_PHASE'           : indi_allsky_config.get('NIGHT_MOONMODE_PHASE', 50),
            'KEOGRAM_ANGLE'                  : indi_allsky_config.get('KEOGRAM_ANGLE', 0),
            'KEOGRAM_H_SCALE'                : indi_allsky_config.get('KEOGRAM_H_SCALE', 100),
            'KEOGRAM_V_SCALE'                : indi_allsky_config.get('KEOGRAM_V_SCALE', 33),
            'KEOGRAM_LABEL'                  : indi_allsky_config.get('KEOGRAM_LABEL', True),
            'STARTRAILS_MAX_ADU'             : indi_allsky_config.get('STARTRAILS_MAX_ADU', 50),
            'STARTRAILS_MASK_THOLD'          : indi_allsky_config.get('STARTRAILS_MASK_THOLD', 190),
            'STARTRAILS_PIXEL_THOLD'         : indi_allsky_config.get('STARTRAILS_PIXEL_THOLD', 0.1),
            'IMAGE_FILE_TYPE'                : indi_allsky_config.get('IMAGE_FILE_TYPE', 'jpg'),
            'IMAGE_FILE_COMPRESSION__JPG'    : indi_allsky_config.get('IMAGE_FILE_COMPRESSION', {}).get('jpg', 90),
            'IMAGE_FILE_COMPRESSION__PNG'    : indi_allsky_config.get('IMAGE_FILE_COMPRESSION', {}).get('png', 9),
            'IMAGE_FOLDER'                   : indi_allsky_config.get('IMAGE_FOLDER', '/var/www/html/allsky/images'),
            'IMAGE_FLIP_V'                   : indi_allsky_config.get('IMAGE_FLIP_V', False),
            'IMAGE_FLIP_H'                   : indi_allsky_config.get('IMAGE_FLIP_H', False),
            'IMAGE_SCALE'                    : indi_allsky_config.get('IMAGE_SCALE', 100),
            'IMAGE_SAVE_RAW'                 : indi_allsky_config.get('IMAGE_SAVE_RAW', False),
            'IMAGE_GRAYSCALE'                : indi_allsky_config.get('IMAGE_GRAYSCALE', False),
            'IMAGE_EXPIRE_DAYS'              : indi_allsky_config.get('IMAGE_EXPIRE_DAYS', 30),
            'FFMPEG_FRAMERATE'               : indi_allsky_config.get('FFMPEG_FRAMERATE', 25),
            'FFMPEG_BITRATE'                 : indi_allsky_config.get('FFMPEG_BITRATE', '2500k'),
            'TEXT_PROPERTIES__FONT_FACE'     : indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_FACE', 'FONT_HERSHEY_SIMPLEX'),
            'TEXT_PROPERTIES__FONT_HEIGHT'   : indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_HEIGHT', 30),
            'TEXT_PROPERTIES__FONT_X'        : indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_X', 15),
            'TEXT_PROPERTIES__FONT_Y'        : indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_Y', 30),
            'TEXT_PROPERTIES__FONT_SCALE'    : indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_SCALE', 0.8),
            'TEXT_PROPERTIES__FONT_THICKNESS': indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_THICKNESS', 1),
            'TEXT_PROPERTIES__FONT_OUTLINE'  : indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_OUTLINE', True),
            'ORB_PROPERTIES__RADIUS'         : indi_allsky_config.get('ORB_PROPERTIES', {}).get('RADIUS', 9),
            'FILETRANSFER__CLASSNAME'        : indi_allsky_config.get('FILETRANSFER', {}).get('CLASSNAME', 'pycurl_sftp'),
            'FILETRANSFER__HOST'             : indi_allsky_config.get('FILETRANSFER', {}).get('HOST', ''),
            'FILETRANSFER__PORT'             : indi_allsky_config.get('FILETRANSFER', {}).get('PORT', 0),
            'FILETRANSFER__USERNAME'         : indi_allsky_config.get('FILETRANSFER', {}).get('USERNAME', ''),
            'FILETRANSFER__PASSWORD'         : indi_allsky_config.get('FILETRANSFER', {}).get('PASSWORD', ''),
            'FILETRANSFER__TIMEOUT'          : indi_allsky_config.get('FILETRANSFER', {}).get('TIMEOUT', 5.0),
            'FILETRANSFER__REMOTE_IMAGE_NAME'         : indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_IMAGE_NAME', 'image.{0}'),
            'FILETRANSFER__REMOTE_IMAGE_FOLDER'       : indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_IMAGE_FOLDER', '/tmp'),
            'FILETRANSFER__REMOTE_VIDEO_FOLDER'       : indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_VIDEO_FOLDER', '/tmp'),
            'FILETRANSFER__REMOTE_KEOGRAM_FOLDER'     : indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_KEOGRAM_FOLDER', '/tmp'),
            'FILETRANSFER__REMOTE_STARTRAIL_FOLDER'   : indi_allsky_config.get('FILETRANSFER', {}).get('REMOTE_STARTRAIL_FOLDER', '/tmp'),
            'FILETRANSFER__UPLOAD_IMAGE'     : indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE', False),
            'FILETRANSFER__UPLOAD_VIDEO'     : indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_VIDEO', False),
            'FILETRANSFER__UPLOAD_KEOGRAM'   : indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_KEOGRAM', False),
            'FILETRANSFER__UPLOAD_STARTRAIL' : indi_allsky_config.get('FILETRANSFER', {}).get('UPLOAD_STARTRAIL', False),
        }


        # ADU_ROI
        try:
            form_data['ADU_ROI_X1'] = indi_allsky_config.get('ADU_ROI', [])[0]
        except IndexError:
            form_data['ADU_ROI_X1'] = 0

        try:
            form_data['ADU_ROI_Y1'] = indi_allsky_config.get('ADU_ROI', [])[1]
        except IndexError:
            form_data['ADU_ROI_Y1'] = 0

        try:
            form_data['ADU_ROI_X2'] = indi_allsky_config.get('ADU_ROI', [])[2]
        except IndexError:
            form_data['ADU_ROI_X2'] = 0

        try:
            form_data['ADU_ROI_Y2'] = indi_allsky_config.get('ADU_ROI', [])[3]
        except IndexError:
            form_data['ADU_ROI_Y2'] = 0


        # IMAGE_CROP_ROI
        try:
            form_data['IMAGE_CROP_ROI_X1'] = indi_allsky_config.get('IMAGE_CROP_ROI', [])[0]
        except IndexError:
            form_data['IMAGE_CROP_ROI_X1'] = 0

        try:
            form_data['IMAGE_CROP_ROI_Y1'] = indi_allsky_config.get('IMAGE_CROP_ROI', [])[1]
        except IndexError:
            form_data['IMAGE_CROP_ROI_Y1'] = 0

        try:
            form_data['IMAGE_CROP_ROI_X2'] = indi_allsky_config.get('IMAGE_CROP_ROI', [])[2]
        except IndexError:
            form_data['IMAGE_CROP_ROI_X2'] = 0

        try:
            form_data['IMAGE_CROP_ROI_Y2'] = indi_allsky_config.get('IMAGE_CROP_ROI', [])[3]
        except IndexError:
            form_data['IMAGE_CROP_ROI_Y2'] = 0



        # Font color
        text_properties__font_color = indi_allsky_config.get('TEXT_PROPERTIES', {}).get('FONT_COLOR', [200, 200, 200])
        text_properties__font_color_str = [str(x) for x in text_properties__font_color]
        form_data['TEXT_PROPERTIES__FONT_COLOR'] = ','.join(text_properties__font_color_str)

        # Sun orb color
        orb_properties__sun_color = indi_allsky_config.get('ORB_PROPERTIES', {}).get('SUN_COLOR', [255, 255, 255])
        orb_properties__sun_color_str = [str(x) for x in orb_properties__sun_color]
        form_data['ORB_PROPERTIES__SUN_COLOR'] = ','.join(orb_properties__sun_color_str)

        # Moon orb color
        orb_properties__moon_color = indi_allsky_config.get('ORB_PROPERTIES', {}).get('MOON_COLOR', [128, 128, 128])
        orb_properties__moon_color_str = [str(x) for x in orb_properties__moon_color]
        form_data['ORB_PROPERTIES__MOON_COLOR'] = ','.join(orb_properties__moon_color_str)


        objects = {
            'form_config' : IndiAllskyConfigForm(data=form_data),
        }

        return objects


class AjaxConfigView(View):
    methods = ['POST']

    def dispatch_request(self):
        form_config = IndiAllskyConfigForm(data=request.json)

        if not form_config.validate():
            form_errors = form_config.errors  # this must be a property
            form_errors['form_global'] = ['Please fix the errors above']
            return jsonify(form_errors), 400


        # form passed validation

        # no need to catch PermissionError here
        with io.open(app.config['INDI_ALLSKY_CONFIG'], 'r') as f_config_file:
            try:
                # try to preserve data order
                indi_allsky_config = json.loads(f_config_file.read(), object_pairs_hook=OrderedDict)
            except json.JSONDecodeError as e:
                app.logger.error('Error decoding json: %s', str(e))
                return jsonify({}), 400


        # sanity check
        if not indi_allsky_config.get('CCD_CONFIG'):
            indi_allsky_config['CCD_CONFIG'] = {}

        if not indi_allsky_config['CCD_CONFIG'].get('NIGHT'):
            indi_allsky_config['CCD_CONFIG']['NIGHT'] = {}

        if not indi_allsky_config['CCD_CONFIG'].get('MOONMODE'):
            indi_allsky_config['CCD_CONFIG']['MOONMODE'] = {}

        if not indi_allsky_config['CCD_CONFIG'].get('DAY'):
            indi_allsky_config['CCD_CONFIG']['DAY'] = {}

        if not indi_allsky_config.get('IMAGE_FILE_COMPRESSION'):
            indi_allsky_config['IMAGE_FILE_COMPRESSION'] = {}

        if not indi_allsky_config.get('TEXT_PROPERTIES'):
            indi_allsky_config['TEXT_PROPERTIES'] = {}

        if not indi_allsky_config.get('ORB_PROPERTIES'):
            indi_allsky_config['ORB_PROPERTIES'] = {}

        if not indi_allsky_config.get('FILETRANSFER'):
            indi_allsky_config['FILETRANSFER'] = {}


        # update data
        indi_allsky_config['CCD_CONFIG']['NIGHT']['GAIN']          = int(request.json['CCD_CONFIG__NIGHT__GAIN'])
        indi_allsky_config['CCD_CONFIG']['NIGHT']['BINNING']       = int(request.json['CCD_CONFIG__NIGHT__BINNING'])
        indi_allsky_config['CCD_CONFIG']['MOONMODE']['GAIN']       = int(request.json['CCD_CONFIG__MOONMODE__GAIN'])
        indi_allsky_config['CCD_CONFIG']['MOONMODE']['BINNING']    = int(request.json['CCD_CONFIG__MOONMODE__BINNING'])
        indi_allsky_config['CCD_CONFIG']['DAY']['GAIN']            = int(request.json['CCD_CONFIG__DAY__GAIN'])
        indi_allsky_config['CCD_CONFIG']['DAY']['BINNING']         = int(request.json['CCD_CONFIG__DAY__BINNING'])
        indi_allsky_config['CCD_EXPOSURE_MAX']                     = float(request.json['CCD_EXPOSURE_MAX'])
        indi_allsky_config['CCD_EXPOSURE_DEF']                     = float(request.json['CCD_EXPOSURE_DEF'])
        indi_allsky_config['CCD_EXPOSURE_MIN']                     = float(request.json['CCD_EXPOSURE_MIN'])
        indi_allsky_config['EXPOSURE_PERIOD']                      = float(request.json['EXPOSURE_PERIOD'])
        indi_allsky_config['AUTO_WB']                              = bool(request.json['AUTO_WB'])
        indi_allsky_config['TARGET_ADU']                           = int(request.json['TARGET_ADU'])
        indi_allsky_config['TARGET_ADU_DEV']                       = int(request.json['TARGET_ADU_DEV'])
        indi_allsky_config['DETECT_STARS']                         = bool(request.json['DETECT_STARS'])
        indi_allsky_config['LOCATION_LATITUDE']                    = int(request.json['LOCATION_LATITUDE'])
        indi_allsky_config['LOCATION_LONGITUDE']                   = int(request.json['LOCATION_LONGITUDE'])
        indi_allsky_config['DAYTIME_CAPTURE']                      = bool(request.json['DAYTIME_CAPTURE'])
        indi_allsky_config['DAYTIME_TIMELAPSE']                    = bool(request.json['DAYTIME_TIMELAPSE'])
        indi_allsky_config['DAYTIME_CONTRAST_ENHANCE']             = bool(request.json['DAYTIME_CONTRAST_ENHANCE'])
        indi_allsky_config['NIGHT_CONTRAST_ENHANCE']               = bool(request.json['NIGHT_CONTRAST_ENHANCE'])
        indi_allsky_config['NIGHT_SUN_ALT_DEG']                    = int(request.json['NIGHT_SUN_ALT_DEG'])
        indi_allsky_config['NIGHT_MOONMODE_ALT_DEG']               = int(request.json['NIGHT_MOONMODE_ALT_DEG'])
        indi_allsky_config['NIGHT_MOONMODE_PHASE']                 = int(request.json['NIGHT_MOONMODE_PHASE'])
        indi_allsky_config['KEOGRAM_ANGLE']                        = int(request.json['KEOGRAM_ANGLE'])
        indi_allsky_config['KEOGRAM_H_SCALE']                      = int(request.json['KEOGRAM_H_SCALE'])
        indi_allsky_config['KEOGRAM_V_SCALE']                      = int(request.json['KEOGRAM_V_SCALE'])
        indi_allsky_config['KEOGRAM_LABEL']                        = bool(request.json['KEOGRAM_LABEL'])
        indi_allsky_config['STARTRAILS_MAX_ADU']                   = int(request.json['STARTRAILS_MAX_ADU'])
        indi_allsky_config['STARTRAILS_MASK_THOLD']                = int(request.json['STARTRAILS_MASK_THOLD'])
        indi_allsky_config['STARTRAILS_PIXEL_THOLD']               = float(request.json['STARTRAILS_PIXEL_THOLD'])
        indi_allsky_config['IMAGE_FILE_TYPE']                      = str(request.json['IMAGE_FILE_TYPE'])
        indi_allsky_config['IMAGE_FILE_COMPRESSION']['jpg']        = int(request.json['IMAGE_FILE_COMPRESSION__JPG'])
        indi_allsky_config['IMAGE_FILE_COMPRESSION']['jpeg']       = int(request.json['IMAGE_FILE_COMPRESSION__JPG'])  # duplicate
        indi_allsky_config['IMAGE_FILE_COMPRESSION']['png']        = int(request.json['IMAGE_FILE_COMPRESSION__PNG'])
        indi_allsky_config['IMAGE_FOLDER']                         = str(request.json['IMAGE_FOLDER'])
        indi_allsky_config['IMAGE_FLIP_V']                         = bool(request.json['IMAGE_FLIP_V'])
        indi_allsky_config['IMAGE_FLIP_H']                         = bool(request.json['IMAGE_FLIP_H'])
        indi_allsky_config['IMAGE_SCALE']                          = int(request.json['IMAGE_SCALE'])
        indi_allsky_config['IMAGE_SAVE_RAW']                       = bool(request.json['IMAGE_SAVE_RAW'])
        indi_allsky_config['IMAGE_GRAYSCALE']                      = bool(request.json['IMAGE_GRAYSCALE'])
        indi_allsky_config['IMAGE_EXPIRE_DAYS']                    = int(request.json['IMAGE_EXPIRE_DAYS'])
        indi_allsky_config['FFMPEG_FRAMERATE']                     = int(request.json['FFMPEG_FRAMERATE'])
        indi_allsky_config['FFMPEG_BITRATE']                       = str(request.json['FFMPEG_BITRATE'])
        indi_allsky_config['TEXT_PROPERTIES']['FONT_FACE']         = str(request.json['TEXT_PROPERTIES__FONT_FACE'])
        indi_allsky_config['TEXT_PROPERTIES']['FONT_HEIGHT']       = int(request.json['TEXT_PROPERTIES__FONT_HEIGHT'])
        indi_allsky_config['TEXT_PROPERTIES']['FONT_X']            = int(request.json['TEXT_PROPERTIES__FONT_X'])
        indi_allsky_config['TEXT_PROPERTIES']['FONT_Y']            = int(request.json['TEXT_PROPERTIES__FONT_Y'])
        indi_allsky_config['TEXT_PROPERTIES']['FONT_SCALE']        = float(request.json['TEXT_PROPERTIES__FONT_SCALE'])
        indi_allsky_config['TEXT_PROPERTIES']['FONT_THICKNESS']    = int(request.json['TEXT_PROPERTIES__FONT_THICKNESS'])
        indi_allsky_config['TEXT_PROPERTIES']['FONT_OUTLINE']      = bool(request.json['TEXT_PROPERTIES__FONT_OUTLINE'])
        indi_allsky_config['ORB_PROPERTIES']['RADIUS']             = int(request.json['ORB_PROPERTIES__RADIUS'])
        indi_allsky_config['FILETRANSFER']['CLASSNAME']            = str(request.json['FILETRANSFER__CLASSNAME'])
        indi_allsky_config['FILETRANSFER']['HOST']                 = str(request.json['FILETRANSFER__HOST'])
        indi_allsky_config['FILETRANSFER']['PORT']                 = int(request.json['FILETRANSFER__PORT'])
        indi_allsky_config['FILETRANSFER']['USERNAME']             = str(request.json['FILETRANSFER__USERNAME'])
        indi_allsky_config['FILETRANSFER']['PASSWORD']             = str(request.json['FILETRANSFER__PASSWORD'])
        indi_allsky_config['FILETRANSFER']['TIMEOUT']              = float(request.json['FILETRANSFER__TIMEOUT'])
        indi_allsky_config['FILETRANSFER']['REMOTE_IMAGE_FOLDER']      = str(request.json['FILETRANSFER__REMOTE_IMAGE_FOLDER'])
        indi_allsky_config['FILETRANSFER']['REMOTE_VIDEO_FOLDER']      = str(request.json['FILETRANSFER__REMOTE_VIDEO_FOLDER'])
        indi_allsky_config['FILETRANSFER']['REMOTE_KEOGRAM_FOLDER']    = str(request.json['FILETRANSFER__REMOTE_KEOGRAM_FOLDER'])
        indi_allsky_config['FILETRANSFER']['REMOTE_STARTRAIL_FOLDER']  = str(request.json['FILETRANSFER__REMOTE_STARTRAIL_FOLDER'])
        indi_allsky_config['FILETRANSFER']['UPLOAD_IMAGE']         = bool(request.json['FILETRANSFER__UPLOAD_IMAGE'])
        indi_allsky_config['FILETRANSFER']['UPLOAD_VIDEO']         = bool(request.json['FILETRANSFER__UPLOAD_VIDEO'])
        indi_allsky_config['FILETRANSFER']['UPLOAD_KEOGRAM']       = bool(request.json['FILETRANSFER__UPLOAD_KEOGRAM'])
        indi_allsky_config['FILETRANSFER']['UPLOAD_STARTRAIL']     = bool(request.json['FILETRANSFER__UPLOAD_STARTRAIL'])


        # ADU_ROI
        adu_roi_x1 = int(request.json['ADU_ROI_X1'])
        adu_roi_y1 = int(request.json['ADU_ROI_Y1'])
        adu_roi_x2 = int(request.json['ADU_ROI_X2'])
        adu_roi_y2 = int(request.json['ADU_ROI_Y2'])

        # the x2 and y2 values must be positive integers in order to be enabled and valid
        if adu_roi_x2 and adu_roi_y2:
            indi_allsky_config['ADU_ROI'] = [adu_roi_x1, adu_roi_y1, adu_roi_x2, adu_roi_y2]
        else:
            indi_allsky_config['ADU_ROI'] = []


        # IMAGE_CROP_ROI
        image_crop_roi_x1 = int(request.json['IMAGE_CROP_ROI_X1'])
        image_crop_roi_y1 = int(request.json['IMAGE_CROP_ROI_Y1'])
        image_crop_roi_x2 = int(request.json['IMAGE_CROP_ROI_X2'])
        image_crop_roi_y2 = int(request.json['IMAGE_CROP_ROI_Y2'])

        # the x2 and y2 values must be positive integers in order to be enabled and valid
        if image_crop_roi_x2 and image_crop_roi_y2:
            indi_allsky_config['IMAGE_CROP_ROI'] = [image_crop_roi_x1, image_crop_roi_y1, image_crop_roi_x2, image_crop_roi_y2]
        else:
            indi_allsky_config['IMAGE_CROP_ROI'] = []



        # TEXT_PROPERTIES FONT_COLOR
        font_color_str = str(request.json['TEXT_PROPERTIES__FONT_COLOR'])
        font_r, font_g, font_b = font_color_str.split(',')
        indi_allsky_config['TEXT_PROPERTIES']['FONT_COLOR'] = [int(font_r), int(font_g), int(font_b)]

        # ORB_PROPERTIES SUN_COLOR
        sun_color_str = str(request.json['ORB_PROPERTIES__SUN_COLOR'])
        sun_r, sun_g, sun_b = sun_color_str.split(',')
        indi_allsky_config['ORB_PROPERTIES']['SUN_COLOR'] = [int(sun_r), int(sun_g), int(sun_b)]

        # ORB_PROPERTIES MOON_COLOR
        moon_color_str = str(request.json['ORB_PROPERTIES__MOON_COLOR'])
        moon_r, moon_g, moon_b = moon_color_str.split(',')
        indi_allsky_config['ORB_PROPERTIES']['MOON_COLOR'] = [int(moon_r), int(moon_g), int(moon_b)]


        # save new config
        try:
            with io.open(app.config['INDI_ALLSKY_CONFIG'], 'w') as f_config_file:
                f_config_file.write(json.dumps(indi_allsky_config, indent=4))
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



bp.add_url_rule('/', view_func=IndexView.as_view('index_view', template_name='index.html'))
bp.add_url_rule('/cameras', view_func=CamerasView.as_view('cameras_view', template_name='cameras.html'))
bp.add_url_rule('/config', view_func=ConfigView.as_view('config_view', template_name='config.html'))
bp.add_url_rule('/ajax/config', view_func=AjaxConfigView.as_view('ajax_config_view'))
bp.add_url_rule('/sqm', view_func=SqmView.as_view('sqm_view', template_name='sqm.html'))
bp.add_url_rule('/loop', view_func=ImageLoopView.as_view('image_loop_view', template_name='loop.html'))
bp.add_url_rule('/js/loop', view_func=JsonImageLoopView.as_view('js_image_loop_view'))
bp.add_url_rule('/chart', view_func=ChartView.as_view('chart_view', template_name='chart.html'))
bp.add_url_rule('/js/chart', view_func=JsonChartView.as_view('js_chart_view'))
