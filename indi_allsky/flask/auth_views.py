from passlib.hash import argon2

from flask import request
from flask import Blueprint
from flask import redirect
from flask import url_for
from is_safe_url import is_safe_url
from flask import abort
#from flask import render_template
#from flask import flash
from flask import jsonify
#from flask import current_app as app

from flask_login import login_user
from flask_login import logout_user
from flask_login import login_required

from .base_views import BaseView
from .base_views import TemplateView

from .models import IndiAllSkyDbUserTable

from .forms import IndiAllskyLoginForm


bp_auth_allsky = Blueprint(
    'auth_indi_allsky',
    __name__,
    template_folder='templates',
    static_folder='static',
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
    static_url_path='static',
)


class LoginView(TemplateView):
    def get_context(self):
        context = super(LoginView, self).get_context()

        context['form_login'] = IndiAllskyLoginForm()

        return context


    def dispatch_request(self):
        if request.method == 'POST':
            return self.post()
        elif request.method == 'GET':
            return super(LoginView, self).dispatch_request()
        else:
            return abort(400)


    def post(self):
        form_login = IndiAllskyLoginForm(data=request.json)

        if not form_login.validate():
            form_errors = form_login.errors  # this must be a property
            form_errors['form_global'] = ['Invalid username or password']
            return jsonify(form_errors), 400


        user = IndiAllskyDbUserTable.query\
            .filter(IndiAllskyDbUserTable.username == request.json['USERNAME'])\
            .first()

        if not user:
            form_errors = form_login.errors  # this must be a property
            form_errors['form_global'] = ['Invalid username or password']
            return jsonify(form_errors), 400

        if not argon2.verify(request.json['PASSWORD'], user.password):
            form_errors = form_login.errors  # this must be a property
            form_errors['form_global'] = ['Invalid username or password']
            return jsonify(form_errors), 400


        login_user(user, remember=True)


        next = request.args.get('next')
        if not is_safe_url(next):
            return jsonify({}), 400



class LogoutView(BaseView):
    decorators = [login_required]

    def dispatch_request(self):
        logout_user()

        return redirect(url_for('indi_allsky.index_view'))


bp_auth_allsky.add_url_rule('/login', view_func=LoginView.as_view('login_view', template_name='login.html'))
bp_auth_allsky.add_url_rule('/logout', view_func=LogoutView.as_view('logout_view'))
