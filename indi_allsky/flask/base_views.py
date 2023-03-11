import io
import math
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import ephem

from flask import session
from flask import render_template
from flask import jsonify
from flask.views import View
from flask import url_for
from flask import current_app as app

from flask_login import current_user

from sqlalchemy.orm.exc import NoResultFound

from .misc import login_optional

from .models import NotificationCategory

from .models import IndiAllSkyDbCameraTable

from .forms import IndiAllskyCameraSelectForm

from .miscDb import miscDb

#from ..exceptions import ConfigSaveException


class BaseView(View):
    decorators = [login_optional]  # auth based on app.config['INDI_ALLSKY_AUTH_ALL_VIEWS']

    def __init__(self, **kwargs):
        super(BaseView, self).__init__(**kwargs)
        from ..config import IndiAllSkyConfig  # prevent circular import

        # not catching exception
        self._indi_allsky_config_obj = IndiAllSkyConfig()

        self.indi_allsky_config = self._indi_allsky_config_obj.config

        self._miscDb = miscDb(self.indi_allsky_config)

        self.s3_prefix = self.getS3Prefix()


    def getS3Prefix(self):
        s3_data = {
            'host'   : self.indi_allsky_config['S3UPLOAD']['HOST'],
            'bucket' : self.indi_allsky_config['S3UPLOAD']['BUCKET'],
            'region' : self.indi_allsky_config['S3UPLOAD']['REGION'],
        }

        try:
            prefix = self.indi_allsky_config['S3UPLOAD']['URL_TEMPLATE'].format(**s3_data)
        except KeyError:
            app.logger.error('Failure to generate S3 prefix')
            return ''
        except ValueError:
            app.logger.error('Failure to generate S3 prefix')
            return ''


        #app.logger.info('S3 Prefix: %s', prefix)

        return prefix


    def getCameraById(self, camera_id):
        if camera_id == -1:
            # see if a camera has been defined since the last run
            camera = IndiAllSkyDbCameraTable.query\
                .order_by(IndiAllSkyDbCameraTable.createDate.desc())\
                .first()

            if camera:
                session['camera_id'] = camera.id
                return camera

            app.logger.warning('No cameras are defined')
            return FakeCamera()


        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()

        return camera


class TemplateView(BaseView):
    def __init__(self, template_name, **kwargs):
        super(TemplateView, self).__init__(**kwargs)
        self.template_name = template_name

        self.camera = None  # set in setupSession()

        self.setupSession()

        self.local_indi_allsky = self.camera.local

        self.check_config(self._indi_allsky_config_obj.config_id)

        # night set in get_astrometric_info()
        self.night = True


    def setupSession(self):
        if session.get('camera_id'):
            self.camera = self.getCameraById(session['camera_id'])
            return

        try:
            self.camera = self.getLatestCamera()
        except NoResultFound:
            # -1 to setup a fake camera object
            session['camera_id'] = -1
            return

        session['camera_id'] = self.camera.id


    def getLatestCamera(self):
        latest_camera = IndiAllSkyDbCameraTable.query\
            .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
            .limit(1)\
            .one()

        return latest_camera


    def render_template(self, context):
        return render_template(self.template_name, **context)


    def dispatch_request(self):
        context = self.get_context()
        return self.render_template(context)


    def get_context(self):
        context = {
            'indi_allsky_status' : self.get_indi_allsky_status(),
            'astrometric_data'   : self.get_astrometric_info(),
            'web_extra_text'     : self.get_web_extra_text(),
            'username_text'      : self.get_user_info(),
        }

        # night set in get_astrometric_info()
        context['night'] = int(self.night)  # javascript does not play well with bools


        camera_default = {
            'CAMERA_SELECT' : session['camera_id'],
        }

        context['form_camera_select'] = IndiAllskyCameraSelectForm(data=camera_default)

        return context


    def check_config(self, config_id):
        try:
            if self.local_indi_allsky:
                # only do this on local devices
                db_config_id = int(self._miscDb.getState('CONFIG_ID'))

                if db_config_id == config_id:
                    return

                self._miscDb.addNotification(
                    NotificationCategory.STATE,
                    'config_id',
                    'Config updated: indi-allsky needs to be reloaded',
                    expire=timedelta(minutes=30),
                )
        except NoResultFound:
            app.logger.error('Unable to get CONFIG_ID')
            return
        except ValueError:
            app.logger.error('Invalid CONFIG_ID')
            return


    def get_indi_allsky_status(self):
        if not self.local_indi_allsky:
            return '<span class="text-muted">REMOTE</span>'


        try:
            watchdog_time = int(self._miscDb.getState('WATCHDOG'))
        except NoResultFound:
            return '<span class="text-warning">UNKNOWN</span>'
        except ValueError:
            return '<span class="text-warning">UNKNOWN</span>'


        now = time.time()

        if now > (watchdog_time + 240):
            return '<span class="text-danger">DOWN</span>'


        ### assuming indi-allsky process is running if we reach this point

        utcnow = datetime.utcnow()  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(self.camera.longitude)
        obs.lat = math.radians(self.camera.latitude)

        sun = ephem.Sun()

        obs.date = utcnow
        sun.compute(obs)
        sun_alt = math.degrees(sun.alt)

        if sun_alt > self.camera.nightSunAlt:
            night = False
        else:
            night = True


        if self.indi_allsky_config.get('FOCUS_MODE', False):
            return '<span class="text-warning">FOCUS MODE</span>'


        if now > (watchdog_time + 300):
            # this notification is only supposed to fire if the program is
            # running normally and the watchdog timestamp is older than 5 minutes
            self._miscDb.addNotification(
                NotificationCategory.GENERAL,
                'watchdog',
                'Watchdog expired.  indi-allsky may be in a failed state.',
                expire=timedelta(minutes=60),
            )


        if not night and not self.indi_allsky_config.get('DAYTIME_CAPTURE', True):
            return '<span class="text-muted">SLEEPING</span>'

        return '<span class="text-success">RUNNING</span>'


    def get_astrometric_info(self):
        if not self.indi_allsky_config:
            return dict()

        data = dict()

        data['latitude'] = self.camera.latitude
        data['longitude'] = self.camera.longitude


        utcnow = datetime.utcnow()  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(self.camera.longitude)
        obs.lat = math.radians(self.camera.latitude)

        sun = ephem.Sun()
        moon = ephem.Moon()

        obs.date = utcnow
        sun.compute(obs)
        moon.compute(obs)

        data['sidereal_time'] = str(obs.sidereal_time())

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
            self.night = False
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


    def get_web_extra_text(self):
        if not self.indi_allsky_config.get('WEB_EXTRA_TEXT'):
            return str()


        web_extra_text_p = Path(self.indi_allsky_config['WEB_EXTRA_TEXT'])

        try:
            if not web_extra_text_p.exists():
                app.logger.error('%s does not exist', web_extra_text_p)
                return str()


            if not web_extra_text_p.is_file():
                app.logger.error('%s is not a file', web_extra_text_p)
                return str()


            # Sanity check
            if web_extra_text_p.stat().st_size > 10000:
                app.logger.error('%s is too large', web_extra_text_p)
                return str()

        except PermissionError as e:
            app.logger.error(str(e))
            return str()


        try:
            with io.open(str(web_extra_text_p), 'r') as web_extra_text_f:
                extra_lines_raw = [x.rstrip() for x in web_extra_text_f.readlines()]
                web_extra_text_f.close()
        except PermissionError as e:
            app.logger.error(str(e))
            return str()


        extra_lines = list()
        for line in extra_lines_raw:
            # encapsulate each line in a div
            extra_lines.append('<div>{0:s}</div>'.format(line))

        extra_text = ''.join(extra_lines)
        #app.logger.info('Extra Text: %s', extra_text)

        return extra_text


    def get_user_info(self):
        if not current_user.is_authenticated:
            return '<a href="{0:s}">Login</a>'.format(url_for('auth_indi_allsky.login_view'))

        return '{0:s} <a href="{1:s}">*</a>'.format(current_user.username, url_for('auth_indi_allsky.logout_view'))


class FormView(TemplateView):
    pass


class JsonView(BaseView):
    def dispatch_request(self):
        json_data = self.get_objects()
        return jsonify(json_data)

    def get_objects(self):
        raise NotImplementedError()


# Prior to indi-allsky being started, no cameras are defined
# This class provides the minimum viable product until a real camera is defined
class FakeCamera(object):
    id = -1
    local = True
    latitude = 0.0
    longitude = 0.0
    nightSunAlt = 0.0

