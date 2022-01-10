from flask import render_template
#from flask import request
from flask import Blueprint

from flask import current_app as app

bp = Blueprint('indi-allsky', __name__, template_folder='templates', url_prefix='/')

#from .models import Foo


@bp.route('/')
@bp.route('/index')
def index():
    return render_template('index.html')
