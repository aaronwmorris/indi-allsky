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

        self.camera = None

        ### Any non-TemplateView that needs camera related variables needs to call cameraSetup(camera_id=camera_id)
        ### This means the camera_id variable needs to be passed to the view via parameter or form element


    def cameraSetup(self, camera_id=None):
        if not self.camera:
            self.camera = self.getCameraById(camera_id)

        self.local_indi_allsky = self.camera.local
        self.getSunSetDate()

        self.daytime_capture = self.camera.daytime_capture
        self.daytime_capture_save = self.camera.daytime_capture_save
        self.capture_pause = self.camera.capture_pause

        self.s3_prefix = self.camera.s3_prefix
        self.web_nonlocal_images = self.camera.web_nonlocal_images
        self.web_local_images_admin = self.camera.web_local_images_admin

        if self.camera.data:
            self.camera_data = dict(self.camera.data)
        else:
            self.camera_data = dict()

        camera_time_offset = self.camera.utc_offset - datetime.now().astimezone().utcoffset().total_seconds()
        self.camera_now = datetime.now() + timedelta(seconds=camera_time_offset)


    def getLatestCamera(self):
        # prefer cameras with daytime timelapse enabled
        latest_camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
            .order_by(IndiAllSkyDbCameraTable.daytime_capture_save.desc())\
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


    def getSunSetDate(self):
        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates

        longitude = self.camera.longitude
        latitude = self.camera.latitude
        elevation = self.camera.elevation

        # this can be eventually removed
        if isinstance(elevation, type(None)):
            elevation = 0


        obs = ephem.Observer()
        obs.lon = math.radians(longitude)
        obs.lat = math.radians(latitude)
        obs.elevation = elevation


        # disable atmospheric refraction calcs
        obs.pressure = 0

        sun = ephem.Sun()

        obs.date = utcnow

        obs.horizon = math.radians(self.camera.nightSunAlt)
        sun.compute(obs)

        try:
            self.sun_set_date = obs.next_setting(sun, use_center=True).datetime()
            #app.logger.info('Sun set date: %s', self.sun_set_date)
        except ephem.AlwaysUpError:
            # northern hemisphere
            self.sun_set_date = None
        except ephem.NeverUpError:
            # southern hemisphere
            self.sun_set_date = None


    def get_indi_allsky_status(self):
        data = {}

        if not self.local_indi_allsky:
            data['status'] = '<span class="text-secondary">REMOTE</span>'
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


        try:
            status = int(self._miscDb.getState('STATUS'))
        except NoResultFound:
            # legacy
            data['status'] = '<span class="text-success">RUNNING</span>'
            return data
        except ValueError:
            # legacy
            data['status'] = '<span class="text-danger">UNKNOWN</span>'
            return data


        if status == constants.STATUS_RUNNING:
            data['status'] = '<span class="text-success">RUNNING</span>'
        elif status == constants.STATUS_SLEEPING:
            data['status'] = '<span class="text-muted">SLEEPING</span>'
        elif status == constants.STATUS_RELOADING:
            data['status'] = '<span class="text-warning">RELOADING</span>'
        elif status == constants.STATUS_STARTING:
            data['status'] = '<span class="text-info">STARTING</span>'
        elif status == constants.STATUS_STOPPING:
            data['status'] = '<span class="text-primary">STOPPING</span>'
        elif status == constants.STATUS_STOPPED:
            data['status'] = '<span class="text-primary">STOPPED</span>'
        elif status == constants.STATUS_PAUSED:
            data['status'] = '<span class="text-muted">PAUSED</span>'
        elif status == constants.STATUS_NOCAMERA:
            data['status'] = '<span class="text-danger">NO CAMERA</span>'
        elif status == constants.STATUS_CAMERAERROR:
            data['status'] = '<span class="text-danger">CAMERA ERROR</span>'
        elif status == constants.STATUS_NOINDISERVER:
            data['status'] = '<span class="text-danger">NO INDISERVER</span>'
        else:
            data['status'] = '<span class="text-danger">UNKNOWN</span>'

        return data


    def get_camera_info(self):
        data = {
            'camera_name' : str(self.camera.name),
            'camera_friendly_name' : str(self.camera.friendlyName),
            'location' : str(self.camera.location),
            'owner' : str(self.camera.owner),
            'lens_name' : str(self.camera.lensName),
        }


        if isinstance(self.camera.alt, type(None)):
            data['alt'] = 0
        else:
            data['alt'] = float(self.camera.alt)

        if isinstance(self.camera.az, type(None)):
            data['az'] = 0
        else:
            data['az'] = float(self.camera.az)


        return data


    def get_astrometric_info(self):
        if not self.indi_allsky_config:
            return dict()


        longitude = self.camera.longitude
        latitude = self.camera.latitude
        elevation = self.camera.elevation
        camera_utc_offset = self.camera.utc_offset

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

        # disable atmospheric refraction calcs
        obs.pressure = 0

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
        if sun_alt > self.camera.nightSunAlt:
            data['mode'] = 'Day'
            self.night = False
        else:
            data['mode'] = 'Night'
            self.night = True



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


        # html glyphs for moon phases
        moon_glyphs_waxing = ['&#127761;', '&#127762;', '&#127763;', '&#127764;', '&#127765;']
        moon_glyphs_waning = ['&#127765;', '&#127766;', '&#127767;', '&#127768;', '&#127761;']

        if latitude < 0:
            # southern hemisphere perspective
            moon_glyphs_waxing, moon_glyphs_waning = moon_glyphs_waning, moon_glyphs_waxing
            moon_glyphs_waxing.reverse()
            moon_glyphs_waning.reverse()


        if moon_cycle_percent <= 50:
            # waxing
            data['moon_glyph'] = moon_glyphs_waxing[round(moon_phase_percent / (100 / (len(moon_glyphs_waxing) - 1)))]
        else:
            # waning
            data['moon_glyph'] = moon_glyphs_waning[round((100 - moon_phase_percent) / (100 / (len(moon_glyphs_waning) - 1)))]


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            obs.horizon = math.radians(self.indi_allsky_config['NIGHT_SUN_ALT_DEG'])
            if self.night:
                mode_next_change_date = obs.next_rising(sun).datetime()
            else:
                mode_next_change_date = obs.next_setting(sun).datetime()

            data['mode_next_change'] = (mode_next_change_date + timedelta(seconds=camera_utc_offset)).strftime('%H:%M')
            data['mode_next_change_h'] = (mode_next_change_date - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            data['mode_next_change'] = '--:--'
            data['mode_next_change_h'] = 0.0
        except ephem.AlwaysUpError:
            data['mode_next_change'] = '--:--'
            data['mode_next_change_h'] = 0.0


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            sun_next_rise_date = obs.next_rising(sun).datetime()
            data['sun_next_rise'] = (sun_next_rise_date + timedelta(seconds=camera_utc_offset)).strftime('%H:%M')
            data['sun_next_rise_h'] = (sun_next_rise_date - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            data['sun_next_rise'] = '--:--'
            data['sun_next_rise_h'] = 0.0
        except ephem.AlwaysUpError:
            data['sun_next_rise'] = '--:--'
            data['sun_next_rise_h'] = 0.0


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            sun_next_set_date = obs.next_setting(sun).datetime()
            data['sun_next_set'] = (sun_next_set_date + timedelta(seconds=camera_utc_offset)).strftime('%H:%M')
            data['sun_next_set_h'] = (sun_next_set_date - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            data['sun_next_set'] = '--:--'
            data['sun_next_set_h'] = 0.0
        except ephem.AlwaysUpError:
            data['sun_next_set'] = '--:--'
            data['sun_next_set_h'] = 0.0


        obs.date = utcnow  # reset
        moon.compute(obs)

        try:
            moon_next_rise_date = obs.next_rising(moon).datetime()
            data['moon_next_rise'] = (moon_next_rise_date + timedelta(seconds=camera_utc_offset)).strftime('%H:%M')
            data['moon_next_rise_h'] = (moon_next_rise_date - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            data['moon_next_rise'] = '--:--'
            data['moon_next_rise_h'] = 0.0
        except ephem.AlwaysUpError:
            data['moon_next_rise'] = '--:--'
            data['moon_next_rise_h'] = 0.0


        obs.date = utcnow  # reset
        moon.compute(obs)

        try:
            moon_next_set_date = obs.next_setting(moon).datetime()
            data['moon_next_set'] = (moon_next_set_date + timedelta(seconds=camera_utc_offset)).strftime('%H:%M')
            data['moon_next_set_h'] = (moon_next_set_date - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            data['moon_next_set'] = '--:--'
            data['moon_next_set_h'] = 0.0
        except ephem.AlwaysUpError:
            data['moon_next_set'] = '--:--'
            data['moon_next_set_h'] = 0.0


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            obs.horizon = math.radians(-18.0)
            sun_next_astro_twilight_rise_date = obs.next_rising(sun).datetime()
            data['sun_next_astro_twilight_rise'] = (sun_next_astro_twilight_rise_date + timedelta(seconds=camera_utc_offset)).strftime('%H:%M')
            data['sun_next_astro_twilight_rise_h'] = (sun_next_astro_twilight_rise_date - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            data['sun_next_astro_twilight_rise'] = '--:--'
            data['sun_next_astro_twilight_rise_h'] = 0.0
        except ephem.AlwaysUpError:
            data['sun_next_astro_twilight_rise'] = '--:--'
            data['sun_next_astro_twilight_rise_h'] = 0.0


        obs.date = utcnow  # reset
        sun.compute(obs)

        try:
            obs.horizon = math.radians(-18.0)
            sun_next_astro_twilight_set_date = obs.next_setting(sun).datetime()
            data['sun_next_astro_twilight_set'] = (sun_next_astro_twilight_set_date + timedelta(seconds=camera_utc_offset)).strftime('%H:%M')
            data['sun_next_astro_twilight_set_h'] = (sun_next_astro_twilight_set_date - utcnow.replace(tzinfo=None)).total_seconds() / 3600
        except ephem.NeverUpError:
            data['sun_next_astro_twilight_set'] = '--:--'
            data['sun_next_astro_twilight_set_h'] = 0.0
        except ephem.AlwaysUpError:
            data['sun_next_astro_twilight_set'] = '--:--'
            data['sun_next_astro_twilight_set_h'] = 0.0


        #obs.horizon = math.radians(0.0)  # reset
        #app.logger.info('Astrometric data: %s', data)

        return data


    def get_aurora_info(self):
        if not self.camera_data:
            data = {
                'aurora_data_status' : 'No data',
                'kpindex' : 0.0,
                'kpindex_status' : 'No data',  # legacy
                'kpindex_trend' : '',
                'kpindex_rating' : '',
                'ovation_max' : 0,
                'ovation_max_status' : 'No data',  # legacy
                'aurora_mag_bt' : 0.0,
                'aurora_mag_gsm_bz' : 0.0,
                'aurora_n_hemi_gw' : 0.0,
                'aurora_s_hemi_gw' : 0.0,
                'aurora_plasma_density' : 0.0,
                'aurora_plasma_speed' : 0.0,
                'aurora_plasma_temp' : 0,
            }
            return data


        kpindex_current = float(self.camera_data.get('KPINDEX_CURRENT', 0))
        kpindex_coef = float(self.camera_data.get('KPINDEX_COEF', 0))
        ovation_max = int(self.camera_data.get('OVATION_MAX', 0))
        aurora_mag_bt = float(self.camera_data.get('AURORA_MAG_BT', 0.0))
        aurora_mag_gsm_bz = float(self.camera_data.get('AURORA_MAG_GSM_BZ', 0.0))
        aurora_plasma_density = float(self.camera_data.get('AURORA_PLASMA_DENSITY', 0.0))
        aurora_plasma_speed = float(self.camera_data.get('AURORA_PLASMA_SPEED', 0.0))
        aurora_plasma_temp = int(self.camera_data.get('AURORA_PLASMA_TEMP', 0))
        n_hemi_gw = int(self.camera_data.get('AURORA_N_HEMI_GW', 0))
        s_hemi_gw = int(self.camera_data.get('AURORA_S_HEMI_GW', 0))


        data = {
            'aurora_data_status' : '',  # just use this for all statuses
            'kpindex' : kpindex_current,
            'kpindex_status' : '',  # legacy
            'ovation_max' : ovation_max,
            'ovation_max_status' : '',  # legacy
            'aurora_mag_bt' : aurora_mag_bt,
            'aurora_mag_gsm_bz' : aurora_mag_gsm_bz,
            'aurora_plasma_density' : aurora_plasma_density,
            'aurora_plasma_speed' : aurora_plasma_speed,
            'aurora_plasma_temp' : aurora_plasma_temp,
            'aurora_n_hemi_gw' : n_hemi_gw,
            'aurora_s_hemi_gw' : s_hemi_gw,
        }


        now = datetime.now()
        now_minus_6h = now - timedelta(hours=6)

        data_timestamp = int(self.camera_data.get('AURORA_DATA_TS', 0))
        if data_timestamp:
            if data_timestamp < now_minus_6h.timestamp():
                data.update({
                    'aurora_data_status' : '[old]',
                    'kpindex_status' : '[old]',  # legacy
                    'kpindex_trend' : '',
                    'kpindex_rating' : '',
                    'ovation_max_status' : '[old]',  # legacy
                })
                return data


        ### synthetic data below here

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
        data = {
            'smoke_rating' : '',
            'smoke_rating_status' : '',
        }


        if not self.camera_data:
            data['smoke_rating'] = 'No data'
            return data


        #app.logger.info('Smoke data: %s', camera_data)

        data['smoke_rating'] = constants.SMOKE_RATING_MAP_STR[self.camera_data.get('SMOKE_RATING', constants.SMOKE_RATING_NODATA)]


        now = datetime.now()
        now_minus_24h = now - timedelta(hours=24)

        data_timestamp = int(self.camera_data.get('SMOKE_DATA_TS', 0))
        if data_timestamp:
            if data_timestamp < now_minus_24h.timestamp():
                data['smoke_rating_status'] = '[old]'

        return data


    def validate_longitude_timezone(self):
        # The theory behind timezones is the sun should be relatively near zenith at noon
        # If there is significant (6+ hours) offset between noon and the suns next transit, the longitude is probably wrong

        now = datetime.now()
        utc_offset = now.astimezone().utcoffset()


        noon = datetime.strptime(now.strftime('%Y%m%d12'), '%Y%m%d%H')
        midnight = datetime.strptime(now.strftime('%Y%m%d00'), '%Y%m%d%H')
        midnight_utc = midnight - utc_offset


        obs = ephem.Observer()
        obs.lon = math.radians(self.indi_allsky_config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.indi_allsky_config['LOCATION_LATITUDE'])

        sun = ephem.Sun()

        obs.date = midnight_utc
        sun.compute(obs)


        next_sun_transit = obs.next_transit(sun)
        local_next_sun_transit = next_sun_transit.datetime() + utc_offset


        if noon > local_next_sun_transit:
            transit_noon_diff_hours = (noon - local_next_sun_transit).seconds / 3600
        else:
            transit_noon_diff_hours = (local_next_sun_transit - noon).seconds / 3600


        if transit_noon_diff_hours < 6:
            return True

        return False


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


    def _load_detection_mask(self):
        import cv2
        from multiprocessing import Value
        from ..maskProcessing import MaskProcessor


        detect_mask = self.indi_allsky_config.get('DETECT_MASK', '')

        if not detect_mask:
            app.logger.warning('No detection mask defined')
            return


        detect_mask_p = Path(detect_mask)

        try:
            if not detect_mask_p.exists():
                app.logger.error('%s does not exist', detect_mask_p)
                return


            if not detect_mask_p.is_file():
                app.logger.error('%s is not a file', detect_mask_p)
                return

        except PermissionError as e:
            app.logger.error(str(e))
            return

        mask_data = cv2.imread(str(detect_mask_p), cv2.IMREAD_GRAYSCALE)  # mono
        if isinstance(mask_data, type(None)):
            app.logger.error('%s is not a valid image', detect_mask_p)
            return


        app.logger.info('Loaded detection mask: %s', detect_mask_p)

        ### any compression artifacts will be set to black
        #mask_data[mask_data < 255] = 0  # did not quite work


        bin_v = Value('i', 1)  # always assume bin 1
        mask_processor = MaskProcessor(
            self.indi_allsky_config,
            bin_v,
        )


        # masks need to be rotated, flipped, cropped for post-processed images
        mask_processor.image = mask_data


        if self.indi_allsky_config.get('IMAGE_ROTATE'):
            mask_processor.rotate_90()


        # rotation
        if self.indi_allsky_config.get('IMAGE_ROTATE_ANGLE'):
            mask_processor.rotate_angle()


        # verticle flip
        if self.indi_allsky_config.get('IMAGE_FLIP_V'):
            mask_processor.flip_v()


        # horizontal flip
        if self.indi_allsky_config.get('IMAGE_FLIP_H'):
            mask_processor.flip_h()


        # crop
        if self.indi_allsky_config.get('IMAGE_CROP_ROI'):
            mask_processor.crop_image()


        # scale
        if self.indi_allsky_config['IMAGE_SCALE'] and self.indi_allsky_config['IMAGE_SCALE'] != 100:
            mask_processor.scale_image()


        return mask_processor.image


class TemplateView(BaseView):

    def __init__(self, template_name, **kwargs):
        super(TemplateView, self).__init__(**kwargs)
        self.template_name = template_name

        self.setupSession()
        self.cameraSetup()

        self.check_config(self._indi_allsky_config_obj)

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

        #app.logger.info('Status data: %s', status_data)

        context = {
            'status_text'        : self.get_status_text(status_data) + self.get_web_extra_text(),
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


    def check_config(self, config_obj):
        try:
            if self.local_indi_allsky:
                # only do this on local devices
                db_config_id = int(self._miscDb.getState('CONFIG_ID'))

                if db_config_id == config_obj.config_id:
                    return

                # wait 10 minutes to notify when a new config is saved
                utcnow = datetime.now(tz=timezone.utc).replace(tzinfo=None)
                if config_obj.createDate.timestamp() + 600 >= utcnow.timestamp():
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


    def setupSession(self):
        if session.get('camera_id'):
            self.camera = self.getCameraById(session['camera_id'])
            return

        try:
            self.camera = self.getLatestCamera()
        except NoResultFound:
            self.camera = FakeCamera()

        session['camera_id'] = self.camera.id


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
    nightSunAlt = -6.0
    alt = 0.0
    az = 0.0
    owner = ''
    location = ''
    lensName = ''
    name = ''
    friendlyName = ''
    s3_prefix = ''
    daytime_capture = True
    daytime_capture_save = True
    daytime_timelapse = True
    capture_pause = False
    web_nonlocal_images = False
    web_local_images_admin = False
    utc_offset = 0
    minGain = -1
    maxGain = -1
    minExposure = -1.0
    maxExposure = -1.0
    data = {}

