import io
import math
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import json
import psutil
import hashlib
import ephem
from collections import OrderedDict

from flask import render_template
from flask import jsonify
from flask.views import View

from flask import current_app as app

from sqlalchemy.orm.exc import NoResultFound

from .models import NotificationCategory

from .models import IndiAllSkyDbCameraTable

from .miscDb import miscDb



class BaseView(View):

    def __init__(self, **kwargs):
        super(BaseView, self).__init__(**kwargs)

        self.indi_allsky_config, self.indi_allsky_config_md5 = self.get_indi_allsky_config()

        self._miscDb = miscDb(self.indi_allsky_config)


    def get_indi_allsky_config(self):
        with io.open(app.config['INDI_ALLSKY_CONFIG'], 'r') as f_config_file:
            config = f_config_file.read()

            try:
                indi_allsky_config = json.loads(config, object_pairs_hook=OrderedDict)
            except json.JSONDecodeError as e:
                app.logger.error('Error decoding json: %s', str(e))
                return dict()

            config_md5 = hashlib.md5(config.encode())

        return indi_allsky_config, config_md5


    def get_indiallsky_pid(self):
        indi_allsky_pid_p = Path(app.config['INDI_ALLSKY_PID'])


        try:
            with io.open(str(indi_allsky_pid_p), 'r') as pid_f:
                pid = pid_f.readline()
                pid = pid.rstrip()
        except FileNotFoundError:
            return False, None
        except PermissionError:
            return None, None


        pid_mtime = indi_allsky_pid_p.stat().st_mtime


        try:
            pid_int = int(pid)
        except ValueError:
            return None, pid_mtime


        return pid_int, pid_mtime


    def getLatestCamera(self):
        latest_camera = IndiAllSkyDbCameraTable.query\
            .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
            .first()

        return latest_camera.id


class TemplateView(BaseView):
    def __init__(self, template_name, **kwargs):
        super(TemplateView, self).__init__(**kwargs)

        self.check_config(self.indi_allsky_config_md5)

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
            'web_extra_text'     : self.get_web_extra_text(),
        }
        return context


    def check_config(self, web_md5):
        try:
            db_md5 = self._miscDb.getState('CONFIG_MD5')
        except NoResultFound:
            app.logger.error('Unable to get CONFIG_MD5')
            return

        if db_md5 == web_md5.hexdigest():
            return

        self._miscDb.addNotification(
            NotificationCategory.STATE,
            'config_md5',
            'Config updated: indi-allsky needs to be reloaded',
            expire=timedelta(minutes=30),
        )


    def get_indi_allsky_status(self):
        pid, pid_mtime = self.get_indiallsky_pid()

        if isinstance(pid, type(None)):
            return '<span class="text-warning">UNKNOWN</span>'

        if not pid:
            return '<span class="text-danger">DOWN</span>'

        if not psutil.pid_exists(pid):
            return '<span class="text-danger">DOWN</span>'


        ### assuming indi-allsky process is running if we reach this point

        utcnow = datetime.utcnow()  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(self.indi_allsky_config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.indi_allsky_config['LOCATION_LATITUDE'])

        sun = ephem.Sun()

        obs.date = utcnow
        sun.compute(obs)
        sun_alt = math.degrees(sun.alt)

        if sun_alt > self.indi_allsky_config['NIGHT_SUN_ALT_DEG']:
            night = False
        else:
            night = True


        if self.indi_allsky_config.get('FOCUS_MODE', False):
            return '<span class="text-warning">FOCUS MODE</span>'


        if time.time() > (pid_mtime + 300):
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

        data['latitude'] = float(self.indi_allsky_config['LOCATION_LATITUDE'])
        data['longitude'] = float(self.indi_allsky_config['LOCATION_LONGITUDE'])


        utcnow = datetime.utcnow()  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(self.indi_allsky_config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.indi_allsky_config['LOCATION_LATITUDE'])

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


class FormView(TemplateView):
    pass


class JsonView(BaseView):
    def dispatch_request(self):
        json_data = self.get_objects()
        return jsonify(json_data)

    def get_objects(self):
        raise NotImplementedError()




