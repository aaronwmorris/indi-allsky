from flask import render_template
#from flask import request
from flask import Blueprint
from flask.views import View

from flask import current_app as app  # noqa

bp = Blueprint('indi-allsky', __name__, template_folder='templates', url_prefix='/')

from .models import IndiAllSkyDbCameraTable


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


class IndexView(TemplateView):
    pass


bp.add_url_rule('/', view_func=IndexView.as_view('index_view', template_name='index.html'))


class CamerasView(ListView):
    def get_objects(self):
        cameras = IndiAllSkyDbCameraTable.query.all()
        return cameras


bp.add_url_rule('/cameras', view_func=CamerasView.as_view('cameras_view', template_name='cameras.html'))
