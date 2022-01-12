from datetime import datetime
from datetime import timedelta
import io
import re
import json
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


class ImageLoopView(TemplateView):
    pass


class JsonImageLoopView(JsonView):
    def __init__(self):
        self.camera_id = self.getLatestCamera()
        self.limit = 40
        self.hours = 2
        self.sqm_history_minutes = 30
        self.stars_history_minutes = 30
        self.rootpath = '/var/www/html/allsky/'


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

        latest_images = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_hours)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())\
            .limit(self.limit)

        image_list = list()
        for i in latest_images:
            rel_filename = re.sub(r'^{0:s}'.format(self.rootpath), '', i.filename)

            data = {
                'file'  : rel_filename,
                'sqm'   : i.sqm,
                'stars' : i.stars,
            }

            image_list.append(data)

        return image_list


    def getSqmData(self):
        now_minus_minutes = datetime.now() - timedelta(minutes=self.sqm_history_minutes)

        sqm_images = db.session\
            .query(
                func.max(IndiAllSkyDbImageTable.sqm).label('image_max_sqm'),
                func.min(IndiAllSkyDbImageTable.sqm).label('image_min_sqm'),
                func.avg(IndiAllSkyDbImageTable.sqm).label('image_avg_sqm'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
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

        stars_images = db.session\
            .query(
                func.max(IndiAllSkyDbImageTable.stars).label('image_max_stars'),
                func.min(IndiAllSkyDbImageTable.stars).label('image_min_stars'),
                func.avg(IndiAllSkyDbImageTable.stars).label('image_avg_stars'),
            )\
            .join(IndiAllSkyDbImageTable.camera)\
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

        chart_query = IndiAllSkyDbImageTable.query\
            .join(IndiAllSkyDbImageTable.camera)\
            .filter(IndiAllSkyDbCameraTable.id == self.camera_id)\
            .filter(IndiAllSkyDbImageTable.createDate > now_minus_minutes)\
            .order_by(IndiAllSkyDbImageTable.createDate.desc())


        chart_data = list()
        for i in chart_query:
            data = {
                'x' : i.createDate.strftime('%H:%M:%S'),
                'y' : i.sqm,
            }

            chart_data.append(data)

        return chart_data


class ConfigView(FormView):
    def get_objects(self):
        with io.open(app.config['INDI_ALLSKY_CONFIG'], 'r') as f_config_file:
            try:
                indi_allsky_config = json.loads(f_config_file.read())
            except json.JSONDecodeError as e:
                app.logger.error('Error decoding json: %s', str(e))


        form_data = {
            'CCD_EXPOSURE_MAX' : indi_allsky_config['CCD_EXPOSURE_MAX'],
        }

        objects = {
            'form_config' : IndiAllskyConfigForm(data=form_data),
        }

        return objects


class AjaxConfigView(View):
    methods = ['POST']

    def dispatch_request(self):
        form_config = IndiAllskyConfigForm(data=request.json)

        if not form_config.validate():
            return jsonify(form_config.errors), 400


        # form passed validation

        # no need to catch PermissionError here
        with io.open(app.config['INDI_ALLSKY_CONFIG'], 'r') as f_config_file:
            try:
                # try to preserve data order
                indi_allsky_config = json.loads(f_config_file.read(), object_pairs_hook=OrderedDict)
            except json.JSONDecodeError as e:
                app.logger.error('Error decoding json: %s', str(e))
                return jsonify({}), 400

        # update data
        indi_allsky_config['CCD_EXPOSURE_MAX'] = float(request.json['CCD_EXPOSURE_MAX'])

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
bp.add_url_rule('/loop', view_func=ImageLoopView.as_view('image_loop_view', template_name='loop.html'))
bp.add_url_rule('/js/loop', view_func=JsonImageLoopView.as_view('js_image_loop_view'))
bp.add_url_rule('/chart', view_func=ChartView.as_view('chart_view', template_name='chart.html'))
bp.add_url_rule('/js/chart', view_func=JsonChartView.as_view('js_chart_view'))
