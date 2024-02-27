import io
import socket
import math
import time
import ipaddress
import psutil
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from pprint import pformat  # noqa: F401
import ephem

from .. import constants

from flask import request
from flask import session
from flask import render_template
from flask import jsonify
from flask.views import View
from flask import url_for
from flask import current_app as app

from flask_login import current_user

from sqlalchemy.orm.exc import NoResultFound
#from sqlalchemy.sql.expression import true as sa_true
from sqlalchemy.sql.expression import false as sa_false
#from sqlalchemy.sql.expression import null as sa_null

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

        self.camera = None  # set in setupSession()

        self.setupSession()

        self.s3_prefix = self.getS3Prefix()


    def setupSession(self):
        if session.get('camera_id'):
            self.camera = self.getCameraById(session['camera_id'])
            return

        try:
            self.camera = self.getLatestCamera()
        except NoResultFound:
            self.camera = FakeCamera()

        session['camera_id'] = self.camera.id


    def getS3Prefix(self):
        s3_data = {
            'host'      : self.indi_allsky_config['S3UPLOAD']['HOST'],
            'bucket'    : self.indi_allsky_config['S3UPLOAD']['BUCKET'],
            'region'    : self.indi_allsky_config['S3UPLOAD']['REGION'],
            'namespace' : self.indi_allsky_config['S3UPLOAD'].get('NAMESPACE', ''),
        }

        try:
            prefix = self.indi_allsky_config['S3UPLOAD']['URL_TEMPLATE'].format(**s3_data)
        except KeyError as e:
            app.logger.error('Failure to generate S3 prefix: %s', str(e))
            return ''
        except ValueError as e:
            app.logger.error('Failure to generate S3 prefix: %s', str(e))
            return ''


        #app.logger.info('S3 Prefix: %s', prefix)

        return prefix


    def getLatestCamera(self):
        latest_camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
            .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
            .limit(1)\
            .one()

        return latest_camera


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
            .first()

        if not camera:
            # this can happen when cameras are deleted
            session['camera_id'] = -1
            return FakeCamera()

        return camera


    def verify_admin_network(self):
        network_list = list()

        network_list.extend(app.config.get('ADMIN_NETWORKS', []))

        net_info = psutil.net_if_addrs()
        for dev, addr_info in net_info.items():
            if dev == 'lo':
                # skip loopback
                continue

            for addr in addr_info:
                if addr.family == socket.AF_INET:
                    cidr = ipaddress.IPv4Network('0.0.0.0/{0:s}'.format(addr.netmask)).prefixlen
                    network_list.append('{0:s}/{1:d}'.format(addr.address, cidr))
                elif addr.family == socket.AF_INET6:
                    network_list.append('{0:s}/{1:d}'.format(addr.address, 64))  # assume /64 for ipv6
                else:
                    continue


        for net in network_list:
            try:
                admin_network = ipaddress.ip_network(net, strict=False)
            except ValueError:
                app.logger.error('Invalid network: %s', net)
                continue


            if request.headers.get('X-Forwarded-For'):
                remote_addrs = request.headers.get('X-Forwarded-For')
            else:
                remote_addrs = request.remote_addr


            remote_addrs_list = remote_addrs.split(',')

            # we only want to validate the last IP in the list
            client_addr = remote_addrs_list[-1].strip()

            try:
                client_ip = ipaddress.ip_address(client_addr)
            except ValueError:
                app.logger.error('Invalid IP: %s', client_addr)
                continue


            if client_ip in admin_network:
                app.logger.info('Matched client IP %s in admin network %s', str(client_ip), str(admin_network))
                return True


        app.logger.warning('Client IP %s not in any admin network', client_addr)
        return False


class TemplateView(BaseView):
    def __init__(self, template_name, **kwargs):
        super(TemplateView, self).__init__(**kwargs)
        self.template_name = template_name

        self.local_indi_allsky = self.camera.local

        self.check_config(self._indi_allsky_config_obj.config_id)

        self.login_disabled = app.config.get('LOGIN_DISABLED', False)

        # night set in get_astrometric_info()
        self.night = True


    def render_template(self, context):
        return render_template(self.template_name, **context)


    def dispatch_request(self):
        context = self.get_context()
        return self.render_template(context)


    def get_context(self):
        status_data = dict()

        status_data.update(self.get_indi_allsky_status())
        status_data.update(self.get_camera_info())
        status_data.update(self.get_astrometric_info())
        status_data.update(self.get_smoke_info())
        status_data.update(self.get_aurora_info())

        context = {
            'status_text'        : self.get_status_text(status_data),
            'web_extra_text'     : self.get_web_extra_text(),
            'username_text'      : self.get_user_info(),
            'login_disabled'     : self.login_disabled,
        }

        # night set in get_astrometric_info()
        context['night'] = int(self.night)  # javascript does not play well with bools


        camera_default = {
            'CAMERA_SELECT' : session['camera_id'],
        }


        context['camera_count'] = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
            .count()

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
        data = {}

        if not self.local_indi_allsky:
            data['status'] = '<span class="text-muted">REMOTE</span>'
            return data


        try:
            watchdog_time = int(self._miscDb.getState('WATCHDOG'))
        except NoResultFound:
            data['status'] = '<span class="text-warning">UNKNOWN</span>'
            return data
        except ValueError:
            data['status'] = '<span class="text-warning">UNKNOWN</span>'
            return data


        now = time.time()

        if now > (watchdog_time + 600):
            data['status'] = '<span class="text-danger">DOWN</span>'
            return data


        ### assuming indi-allsky process is running if we reach this point
        longitude = self.camera.longitude
        latitude = self.camera.latitude
        elevation = self.camera.elevation

        # this can be eventually removed
        if isinstance(elevation, type(None)):
            elevation = 0


        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(longitude)
        obs.lat = math.radians(latitude)
        obs.elevation = elevation

        sun = ephem.Sun()

        obs.date = utcnow
        sun.compute(obs)
        sun_alt = math.degrees(sun.alt)

        if sun_alt > self.camera.nightSunAlt:
            night = False
        else:
            night = True


        if self.indi_allsky_config.get('FOCUS_MODE', False):
            data['status'] = '<span class="text-warning">FOCUS MODE</span>'
            return data


        if now > (watchdog_time + 600):
            # this notification is only supposed to fire if the program is
            # running normally and the watchdog timestamp is older than 10 minutes
            self._miscDb.addNotification(
                NotificationCategory.GENERAL,
                'watchdog',
                'Watchdog expired.  indi-allsky may be in a failed state.',
                expire=timedelta(minutes=60),
            )


        if not night and not self.indi_allsky_config.get('DAYTIME_CAPTURE', True):
            data['status'] = '<span class="text-muted">SLEEPING</span>'
            return data


        data['status'] = '<span class="text-success">RUNNING</span>'
        return data


    def get_camera_info(self):
        data = {
            'camera_name' : str(self.camera.name),
            'camera_friendly_name' : str(self.camera.friendlyName),
            'location' : str(self.camera.location),
            'owner' : str(self.camera.owner),
            'lens_name' : str(self.camera.lensName),
            'alt' : float(self.camera.alt),
            'az' : float(self.camera.az),
        }

        return data


    def get_astrometric_info(self):
        if not self.indi_allsky_config:
            return dict()


        longitude = self.camera.longitude
        latitude = self.camera.latitude
        elevation = self.camera.elevation

        # this can be eventually removed
        if isinstance(elevation, type(None)):
            elevation = 0


        data = dict()

        data['latitude'] = latitude
        data['longitude'] = longitude
        data['elevation'] = elevation


        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        obs = ephem.Observer()
        obs.lon = math.radians(longitude)
        obs.lat = math.radians(latitude)
        obs.elevation = elevation

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
        sun_transit_delta = sun_transit_date - utcnow.replace(tzinfo=None)
        if sun_transit_delta.seconds < 43200:  # 12 hours
            #rising
            data['sun_dir'] = '&nearr;'
        else:
            #setting
            data['sun_dir'] = '&searr;'


        # moon
        moon_alt = math.degrees(moon.alt)
        data['moon_alt'] = moon_alt

        #moon phase
        moon_phase_percent = moon.moon_phase * 100.0
        data['moon_phase'] = moon_phase_percent

        moon_transit_date = obs.next_transit(moon).datetime()
        moon_transit_delta = moon_transit_date - utcnow.replace(tzinfo=None)
        if moon_transit_delta.seconds < 43200:  # 12 hours
            #rising
            data['moon_dir'] = '&nearr;'
        else:
            #setting
            data['moon_dir'] = '&searr;'


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
            data['moon_phase_str'] = 'Waxing'
        else:
            #2, 3
            data['moon_phase_str'] = 'Waning'



        moon_cycle_percent = (sm_angle / math.tau) * 100
        data['moon_cycle_percent'] = moon_cycle_percent

        if moon_cycle_percent <= 50:
            # waxing
            if moon_phase_percent >= 0 and moon_phase_percent < 15:
                data['moon_glyph'] = '&#127761;'
            elif moon_phase_percent >= 15 and moon_phase_percent < 35:
                data['moon_glyph'] = '&#127762;'
            elif moon_phase_percent >= 35 and moon_phase_percent < 65:
                data['moon_glyph'] = '&#127763;'
            elif moon_phase_percent >= 65 and moon_phase_percent < 85:
                data['moon_glyph'] = '&#127764;'
            elif moon_phase_percent >= 85 and moon_phase_percent <= 100:
                data['moon_glyph'] = '&#127765;'
        else:
            # waning
            if moon_phase_percent >= 85 and moon_phase_percent <= 100:
                data['moon_glyph'] = '&#127765;'
            elif moon_phase_percent >= 65 and moon_phase_percent < 85:
                data['moon_glyph'] = '&#127766;'
            elif moon_phase_percent >= 35 and moon_phase_percent < 65:
                data['moon_glyph'] = '&#127767;'
            elif moon_phase_percent >= 15 and moon_phase_percent < 35:
                data['moon_glyph'] = '&#127768;'
            elif moon_phase_percent >= 0 and moon_phase_percent < 15:
                data['moon_glyph'] = '&#127761;'


        #app.logger.info('Astrometric data: %s', data)

        return data


    def get_aurora_info(self):
        camera_data = self.camera.data

        if not camera_data:
            data = {
                'kpindex' : 0.0,
                'kpindex_status' : 'No data',
                'kpindex_trend' : '',
                'kpindex_rating' : '',
                'ovation_max' : 0,
                'ovation_max_status' : 'No data',
            }
            return data


        kpindex_current = float(camera_data.get('KPINDEX_CURRENT'))
        kpindex_coef = float(camera_data.get('KPINDEX_COEF'))
        ovation_max = int(camera_data.get('OVATION_MAX'))


        now = datetime.now()
        now_minus_6h = now - timedelta(hours=6)

        data_timestamp = int(camera_data.get('AURORA_DATA_TS', 0))
        if data_timestamp:
            if data_timestamp < now_minus_6h.timestamp():
                data = {
                    'kpindex' : kpindex_current,
                    'kpindex_status' : '[old]',
                    'kpindex_trend' : '',
                    'kpindex_rating' : '',
                    'ovation_max' : ovation_max,
                    'ovation_max_status' : '[old]',
                }
                return data


        data = {
            'kpindex' : kpindex_current,
            'kpindex_status' : '',
            'ovation_max' : ovation_max,
            'ovation_max_status' : '',
        }



        if kpindex_coef == 0:
            kpindex_trend = ''
        elif kpindex_coef >= 2:
            kpindex_trend = '&nearr;'
        elif kpindex_coef <= 0.5:
            kpindex_trend = '&searr;'
        else:
            kpindex_trend = '&rarr;'


        data['kpindex_trend'] = kpindex_trend


        if kpindex_current == 0:
            data['kpindex_rating'] = ''
        elif kpindex_current > 0 and kpindex_current < 5.0:
            data['kpindex_rating'] = '<span class="text-secondary">LOW</span>'
        elif kpindex_current >= 5.0 and kpindex_current < 6.0:
            data['kpindex_rating'] = '<span class="text-warning">MEDIUM</span>'
        elif kpindex_current >= 6.0 and kpindex_current < 8.0:
            data['kpindex_rating'] = '<span class="text-danger">HIGH</span>'
        elif kpindex_current >= 8.0:
            data['kpindex_rating'] = '<span class="text-danger">VERY HIGH</span>'
        else:
            # this should never happen
            data['kpindex_rating'] = 'ERROR'


        return data


    def get_smoke_info(self):
        camera_data = self.camera.data

        data = {
            'smoke_rating' : '',
            'smoke_rating_status' : '',
        }


        if not camera_data:
            data['smoke_rating'] = 'No data'
            return data


        #app.logger.info('Smoke data: %s', camera_data)

        data['smoke_rating'] = constants.SMOKE_RATING_MAP_STR[camera_data.get('SMOKE_RATING', constants.SMOKE_RATING_NODATA)]


        now = datetime.now()
        now_minus_24h = now - timedelta(hours=24)

        data_timestamp = int(camera_data.get('SMOKE_DATA_TS', 0))
        if data_timestamp:
            if data_timestamp < now_minus_24h.timestamp():
                data['smoke_rating_status'] = '[old]'

        return data


    def get_status_text(self, data):
        status_lines = list()
        for line in self.indi_allsky_config.get('WEB_STATUS_TEMPLATE', 'Status: {status:s}').splitlines():
            # encapsulate each line in a div
            status_lines.append('<div>{0:s}</div>'.format(line))

        status_tmpl = ''.join(status_lines)
        #app.logger.info('Status Text: %s', status_tmpl)
        #app.logger.info('Status data: %s', pformat(data))

        try:
            status_text = status_tmpl.format(**data)
        except KeyError as e:
            app.logger.error('Failure to format status: %s', str(e))
            return 'TEMPLATE ERROR'
        except ValueError as e:
            app.logger.error('Failure to format status: %s', str(e))
            return 'TEMPLATE ERROR'


        return status_text


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
            return '<a href="{0:s}" style="text-decoration: none">Login</a>'.format(url_for('auth_indi_allsky.login_view'))

        return '<a href="{0:s}" style="text-decoration: none">{1:s}</a>'.format(url_for('indi_allsky.user_view'), current_user.username)


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
    elevation = 0
    nightSunAlt = 0.0
    alt = 0.0
    az = 0.0
    owner = ''
    location = ''
    lensName = ''
    name = ''
    friendlyName = ''
    data = {}

