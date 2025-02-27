import time
import math
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import hashlib
import hmac
import json
import tempfile
import shutil


from flask import request
from flask import Blueprint
from flask import jsonify
from flask import current_app as app

#from flask_login import login_required

from .. import constants

from .base_views import BaseView

from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbMiniVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable
from .models import IndiAllSkyDbStarTrailsVideoTable
from .models import IndiAllSkyDbRawImageTable
from .models import IndiAllSkyDbFitsImageTable
from .models import IndiAllSkyDbPanoramaImageTable
from .models import IndiAllSkyDbPanoramaVideoTable
from .models import IndiAllSkyDbThumbnailTable
from .models import IndiAllSkyDbUserTable

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.orm.exc import MultipleResultsFound
from sqlalchemy import and_


bp_syncapi_allsky = Blueprint(
    'syncapi_indi_allsky',
    __name__,
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
)


class SyncApiBaseView(BaseView):
    decorators = []

    model = None
    filename_t = None
    add_function = None

    time_skew = 300  # number of seconds the client is allowed to deviate from server


    def __init__(self, **kwargs):
        super(SyncApiBaseView, self).__init__(**kwargs)

        if self.indi_allsky_config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.parent.joinpath('html', 'images').absolute()


    def dispatch_request(self):
        try:
            #time.sleep(10)  # testing
            self.authorize(request.files['metadata'].stream.read())  # authenticate the request
        except AuthenticationFailure as e:
            app.logger.error('Authentication failure: %s', str(e))
            return jsonify({'error' : 'authentication failed'}), 400


        try:
            if request.method == 'POST':
                return self.post()
            elif request.method == 'PUT':
                return self.put()
            elif request.method == 'DELETE':
                return self.delete()
            elif request.method == 'GET':
                return self.get()
            else:
                return jsonify({}), 400

        except AuthenticationFailure as e:
            app.logger.error('Authentication failure: %s', str(e))
            return jsonify({'error' : 'authentication failed'}), 400


    def post(self, overwrite=False):
        metadata = self.saveMetadata(request.files['metadata'])

        tmp_media_file_p = self.saveMedia(request.files['media'])


        media_file_size = tmp_media_file_p.stat().st_size
        if media_file_size != metadata.get('file_size', -1):
            tmp_media_file_p.unlink()
            raise AuthenticationFailure('Media file size does not match')


        try:
            camera = self.getCamera(metadata)
        except NoResultFound:
            app.logger.error('Camera not found: %s', metadata['camera_uuid'])
            return jsonify({'error' : 'camera not found'}), 400


        try:
            file_entry = self.processPost(camera, metadata, tmp_media_file_p, overwrite=overwrite)
        except EntryExists:
            return jsonify({'error' : 'file_exists'}), 400


        return jsonify({
            'id'   : file_entry.id,
            'url'  : str(file_entry.getUrl(local=True)),
        })


    def put(self, overwrite=True):
        return self.post(overwrite=overwrite)


    def delete(self):
        metadata = self.saveMetadata(request.files['metadata'])
        # no media

        try:
            camera = self.getCamera(metadata)
        except NoResultFound:
            app.logger.error('Camera not found: %s', metadata['camera_uuid'])
            return jsonify({'error' : 'camera not found'}), 400


        try:
            self.deleteFile(metadata['id'], camera.id)
        except EntryMissing:
            return jsonify({'error' : 'file_missing'}), 400

        return jsonify({})


    def get(self):
        metadata = self.saveMetadata(request.files['metadata'])
        # no media

        try:
            camera = self.getCamera(metadata)
        except NoResultFound:
            app.logger.error('Camera not found: %s', metadata['camera_uuid'])
            return jsonify({'error' : 'camera not found'}), 400


        try:
            file_entry = self.getEntry(metadata, camera)
        except EntryMissing:
            return jsonify({'error' : 'file_missing'}), 400

        return jsonify({
            'id'   : file_entry.id,
            'url'  : str(file_entry.getUrl(local=True)),
        })


    def processPost(self, camera, metadata, tmp_file_p, overwrite=False):
        # offset createDate to account for difference between local and remote sites
        metadata['createDate'] += (metadata['utc_offset'] - datetime.now().astimezone().utcoffset().total_seconds())

        d_dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), d_dayDate.strftime('%Y%m%d'))
        if not date_folder.exists():
            date_folder.mkdir(mode=0o755, parents=True)


        if metadata['night']:
            timeofday_str = 'night'
        else:
            timeofday_str = 'day'



        try:
            # delete old entry if it exists
            old_entry = self.model.query\
                .join(self.model.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        self.model.dayDate == d_dayDate,
                        self.model.night == bool(metadata['night']),
                    )
                )\
                .one()


            if not overwrite:
                raise EntryExists()


            old_entry.deleteAsset()

            db.session.delete(old_entry)
            db.session.commit()
        except MultipleResultsFound as e:
            # this should never happen
            raise EntryError('Multiple entries for the same dayDate and night') from e
        except NoResultFound:
            pass


        filename_p = date_folder.joinpath(
            self.filename_t.format(
                camera.id,
                d_dayDate.strftime('%Y%m%d'),
                timeofday_str,
                int(metadata['createDate']),
                tmp_file_p.suffix,  # suffix includes dot
            )
        )

        if filename_p.exists():
            app.logger.warning('Removing orphaned file: %s', filename_p)
            filename_p.unlink()


        # do not sync these metadata keys for now
        exclude_keys = []
        for k in exclude_keys:
            try:
                metadata.pop(k)
            except KeyError:
                pass


        addFunction_method = getattr(self._miscDb, self.add_function)
        new_entry = addFunction_method(
            filename_p,
            camera.id,
            metadata,
        )


        tmp_file_size = tmp_file_p.stat().st_size
        if tmp_file_size != 0:
            # only copy file if it is not empty
            # if the empty file option is selected, this can be expected
            shutil.copy2(str(tmp_file_p), str(filename_p))
            filename_p.chmod(0o644)


        tmp_file_p.unlink()

        app.logger.info('Uploaded file: %s', filename_p)

        return new_entry


    def deleteFile(self, entry_id, camera_id):
        # we do not want to call deleteAsset() here
        try:
            entry = self.model.query\
                .join(IndiAllSkyDbCameraTable)\
                .filter(IndiAllSkyDbCameraTable.id == camera_id)\
                .filter(self.model.id == entry_id)\
                .one()


            entry.deleteFile()

            app.logger.warning('Deleting entry %d', entry.id)
            db.session.delete(entry)
            db.session.commit()
        except NoResultFound:
            raise EntryMissing()


    def getEntry(self, metadata, camera):
        try:
            entry = self.model.query\
                .join(IndiAllSkyDbCameraTable)\
                .filter(IndiAllSkyDbCameraTable.id == camera.id)\
                .filter(self.model.id == metadata['id'])\
                .one()

        except NoResultFound:
            raise EntryMissing()


        return entry


    def saveMetadata(self, metadata_file):
        metadata_file.seek(0)  # rewind file
        metadata_json = json.load(metadata_file)

        # Not updating createDate here incase we need it for authentication

        #app.logger.info('Json: %s', metadata_json)

        return metadata_json


    def saveMedia(self, media_file):
        media_file_p = Path(media_file.filename)  # need this for the extension
        #app.logger.info('File: %s', media_file_p)

        f_tmp_media = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=media_file_p.suffix)
        f_tmp_media.close()

        tmp_media_p = Path(f_tmp_media.name)

        media_file.save(str(tmp_media_p))

        return tmp_media_p


    #def put(self):
    #    #media_file = request.files.get('media')
    #    pass


    def authorize(self, data):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            raise AuthenticationFailure('Missing Authoriation header')

        try:
            bearer, user_hmac_hash = auth_header.split(' ')
        except ValueError:
            raise AuthenticationFailure('Malformed API key')


        try:
            username, received_hmac = user_hmac_hash.split(':')
        except ValueError:
            raise AuthenticationFailure('Malformed API key')


        user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()


        if not user:
            raise AuthenticationFailure('Unknown user')


        apikey = user.getApiKey(app.config['PASSWORD_KEY'])


        time_floor = math.floor(time.time() / self.time_skew)

        # the time on the remote system needs to be plus/minus the time_floor period
        time_floor_list = [
            time_floor,
            time_floor - 1,
            time_floor + 1,
            time_floor - 2,  # large file uploads my take a long time
            time_floor - 3,
            time_floor - 4,
        ]

        for t in time_floor_list:
            #app.logger.info('Time floor: %d', t)

            hmac_message = str(t).encode() + data
            #app.logger.info('Data: %s', hmac_message)

            message_hmac = hmac.new(
                apikey.encode(),
                msg=hmac_message,
                digestmod=hashlib.sha3_512,
            ).hexdigest()

            if hmac.compare_digest(message_hmac, received_hmac):
                break
        else:
            raise AuthenticationFailure('Unable to authenticate API key')


    def getCamera(self, metadata):
        # not catching NoResultFound
        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.uuid == metadata['camera_uuid'])\
            .one()


        if camera.utc_offset != metadata['utc_offset']:
            # update utc offset
            camera.utc_offset = int(metadata['utc_offset'])
            db.session.commit()


        return camera


class SyncApiCameraView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbCameraTable
    filename_t = None
    add_function = 'addCamera_remote'


    def get(self):
        metadata = self.saveMetadata(request.files['metadata'])

        try:
            file_entry = self.getEntry(metadata)
        except EntryMissing:
            return jsonify({'error' : 'camera_missing'}), 400

        return jsonify({
            'id'   : file_entry.id,
        })


    def post(self, overwrite=True):
        metadata = self.saveMetadata(request.files['metadata'])


        camera_entry = self.processPost(None, metadata, None, overwrite=overwrite)

        return jsonify({
            'id'   : camera_entry.id,
        })


    def put(self, overwrite=True):
        return self.post(overwrite=overwrite)


    def getEntry(self, metadata):
        try:
            entry = self.model.query\
                .filter(self.model.id == metadata['id'])\
                .filter(self.model.uuid == metadata['camera_uuid'])\
                .one()

        except NoResultFound:
            raise EntryMissing()


        return entry


    def processPost(self, camera_notUsed, metadata, file_notUsed, overwrite=True):
        addFunction_method = getattr(self._miscDb, self.add_function)
        entry = addFunction_method(
            metadata,
        )

        app.logger.info('Updated camera: %s', entry.uuid)

        return entry


    def delete(self):
        return jsonify({'error' : 'not_implemented'}), 400


class SyncApiBaseImageView(SyncApiBaseView):
    decorators = []

    type_folder = None


    def processPost(self, camera, image_metadata, tmp_file_p, overwrite=False):
        # offset createDate to account for difference between local and remote sites
        image_metadata['createDate'] += (image_metadata['utc_offset'] - datetime.now().astimezone().utcoffset().total_seconds())

        camera_createDate = datetime.fromtimestamp(image_metadata['createDate'])
        folder = self.getImageFolder(camera_createDate, image_metadata['night'], camera)

        date_str = camera_createDate.strftime('%Y%m%d_%H%M%S')
        image_file_p = folder.joinpath(
            self.filename_t.format(
                camera.id,
                date_str,
                tmp_file_p.suffix,
            )
        )


        try:
            # delete old entry if it exists
            old_entry = self.model.query\
                .join(self.model.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        self.model.createDate == camera_createDate,
                    )
                )\
                .one()


            if not overwrite:
                raise EntryExists()


            app.logger.warning('Removing orphaned image entry')
            old_entry.deleteAsset()

            db.session.delete(old_entry)
            db.session.commit()
        except NoResultFound:
            pass



        if image_file_p.exists():
            image_file_p.unlink()


        addFunction_method = getattr(self._miscDb, self.add_function)
        new_entry = addFunction_method(
            image_file_p,
            camera.id,
            image_metadata,
        )


        tmp_file_size = tmp_file_p.stat().st_size
        if tmp_file_size != 0:
            # only copy file if it is not empty
            # if the empty file option is selected, this can be expected
            shutil.copy2(str(tmp_file_p), str(image_file_p))
            image_file_p.chmod(0o644)


        tmp_file_p.unlink()

        app.logger.info('Uploaded image: %s', image_file_p)

        return new_entry


    def getImageFolder(self, exp_date, night, camera):
        if night:
            # images should be written to previous day's folder until noon
            day_ref = exp_date - timedelta(hours=12)
            timeofday_str = 'night'
        else:
            # images should be written to current day's folder
            day_ref = exp_date
            timeofday_str = 'day'


        day_folder = self.image_dir.joinpath(
            'ccd_{0:s}'.format(camera.uuid),
            self.type_folder,
            '{0:s}'.format(day_ref.strftime('%Y%m%d')),
            timeofday_str,
        )

        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)


        hour_str = exp_date.strftime('%d_%H')

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir(mode=0o755)

        return hour_folder


class SyncApiImageView(SyncApiBaseImageView):
    decorators = []

    model = IndiAllSkyDbImageTable
    filename_t = 'ccd{0:d}_{1:s}{2:s}'  # extension includes dot
    add_function = 'addImage'
    type_folder = 'exposures'


    def processPost(self, camera, image_metadata, tmp_file_p, overwrite=False):
        if image_metadata.get('keogram_pixels'):
            # do not offset timestamp
            self._miscDb.add_long_term_keogram_data(
                image_metadata['createDate'],
                camera.id,
                image_metadata['keogram_pixels'],
            )

        return super(SyncApiImageView, self).processPost(camera, image_metadata, tmp_file_p, overwrite=False)


class SyncApiVideoView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbVideoTable
    filename_t = 'allsky-timelapse_ccd{0:d}_{1:s}_{2:s}_{3:d}{4:s}'  # extension includes dot
    add_function = 'addVideo'


class SyncApiMiniVideoView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbMiniVideoTable
    ### filename now includes a timestamp to ensure uniqueness
    filename_t = 'allsky-minitimelapse_ccd{0:d}_{1:s}_{2:s}_{3:d}{4:s}'  # extension includes dot
    add_function = 'addMiniVideo'


class SyncApiKeogramView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbKeogramTable
    filename_t = 'allsky-keogram_ccd{0:d}_{1:s}_{2:s}_{3:d}{4:s}'  # extension includes dot
    add_function = 'addKeogram'


class SyncApiStartrailView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbStarTrailsTable
    filename_t = 'allsky-startrail_ccd{0:d}_{1:s}_{2:s}_{3:d}{4:s}'  # extension includes dot
    add_function = 'addStarTrail'


class SyncApiStartrailVideoView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbStarTrailsVideoTable
    filename_t = 'allsky-startrail_timelapse_ccd{0:d}_{1:s}_{2:s}{3:d}{4:s}'  # extension includes dot
    add_function = 'addStarTrailVideo'


class SyncApiRawImageView(SyncApiBaseImageView):  # image parent
    decorators = []

    model = IndiAllSkyDbRawImageTable
    filename_t = 'raw_ccd{0:d}_{1:s}{2:s}'  # extension includes dot
    add_function = 'addRawImage'
    type_folder = 'export'  # fixme need processImage/getImageFolder function for export folder


class SyncApiFitsImageView(SyncApiBaseImageView):  # image parent
    decorators = []

    model = IndiAllSkyDbFitsImageTable
    filename_t = 'ccd{0:d}_{1:s}{2:s}'  # extension includes dot
    add_function = 'addFitsImage'
    type_folder = 'fits'


class SyncApiPanoramaImageView(SyncApiBaseImageView):  # image parent
    decorators = []

    model = IndiAllSkyDbPanoramaImageTable
    filename_t = 'panorama_ccd{0:d}_{1:s}{2:s}'  # extension includes dot
    add_function = 'addPanoramaImage'
    type_folder = 'panoramas'


class SyncApiPanoramaVideoView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbPanoramaVideoTable
    filename_t = 'allsky-panorama_timelapse_ccd{0:d}_{1:s}_{2:s}{3:d}{4:s}'  # extension includes dot
    add_function = 'addPanoramaVideo'


class SyncApiThumbnailView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbThumbnailTable
    filename_t = '{0:s}{1:s}'  # extension includes dot
    add_function = 'addThumbnail_remote'


    def processPost(self, camera, thumbnail_metadata, tmp_file_p, overwrite=False):
        # offset createDate to account for difference between local and remote sites
        thumbnail_metadata['createDate'] += (thumbnail_metadata['utc_offset'] - datetime.now().astimezone().utcoffset().total_seconds())

        camera_createDate = datetime.fromtimestamp(thumbnail_metadata['createDate'])

        d_dayDate = datetime.strptime(thumbnail_metadata['dayDate'], '%Y%m%d').date()


        if thumbnail_metadata['night']:
            timeofday = 'night'
        else:
            timeofday = 'day'


        if thumbnail_metadata.get('origin', -1) in (
            -1,
            constants.IMAGE,
            constants.PANORAMA_IMAGE,
        ):

            if thumbnail_metadata.get('origin', -1) == constants.PANORAMA_IMAGE:
                type_folder = 'panoramas'
            else:
                type_folder = 'exposures'


            thumbnail_dir_p = self.image_dir.joinpath(
                'ccd_{0:s}'.format(thumbnail_metadata['camera_uuid']),
                type_folder,
                d_dayDate.strftime('%Y%m%d'),
                timeofday,
                camera_createDate.strftime('%d_%H'),
                'thumbnails',
            )
        else:
            # constants.KEOGRAM and constants.STARTRAIL
            thumbnail_dir_p = self.image_dir.joinpath(
                'ccd_{0:s}'.format(thumbnail_metadata['camera_uuid']),
                'timelapse',
                d_dayDate.strftime('%Y%m%d'),
                'thumbnails',
            )


        thumbnail_file_p = thumbnail_dir_p.joinpath(self.filename_t.format(thumbnail_metadata['uuid'], tmp_file_p.suffix))  # suffix includes dot


        if not thumbnail_file_p.exists():
            try:
                # delete old entry if it exists
                old_thumbnail_entry = self.model.query\
                    .filter(self.model.filename == str(thumbnail_file_p))\
                    .one()

                app.logger.warning('Removing orphaned thumbnail entry')
                db.session.delete(old_thumbnail_entry)
                db.session.commit()
            except NoResultFound:
                pass


        else:
            if not overwrite:
                raise EntryExists()

            app.logger.warning('Replacing image')
            thumbnail_file_p.unlink()

            try:
                old_image_entry = self.model.query\
                    .filter(self.model.filename == str(thumbnail_file_p))\
                    .one()

                app.logger.warning('Removing old image entry')
                db.session.delete(old_image_entry)
                db.session.commit()
            except NoResultFound:
                pass


        addFunction_method = getattr(self._miscDb, self.add_function)
        new_entry = addFunction_method(
            thumbnail_file_p,
            camera.id,
            thumbnail_metadata,
        )


        tmp_file_size = tmp_file_p.stat().st_size
        if tmp_file_size != 0:
            # only copy file if it is not empty
            # if the empty file option is selected, this can be expected

            thumbnail_dir_p = thumbnail_file_p.parent
            if not thumbnail_dir_p.exists():
                thumbnail_dir_p.mkdir(mode=0o755, parents=True)

            shutil.copy2(str(tmp_file_p), str(thumbnail_file_p))
            thumbnail_file_p.chmod(0o644)


        tmp_file_p.unlink()

        app.logger.info('Uploaded thumbnail: %s', thumbnail_file_p)

        return new_entry


class EntryExists(Exception):
    pass


class EntryMissing(Exception):
    pass


class AuthenticationFailure(Exception):
    pass


class EntryError(Exception):
    pass


bp_syncapi_allsky.add_url_rule('/sync/v1/camera', view_func=SyncApiCameraView.as_view('syncapi_v1_camera_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/image', view_func=SyncApiImageView.as_view('syncapi_v1_image_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/video', view_func=SyncApiVideoView.as_view('syncapi_v1_video_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/minivideo', view_func=SyncApiMiniVideoView.as_view('syncapi_v1_min_video_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/keogram', view_func=SyncApiKeogramView.as_view('syncapi_v1_keogram_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrail', view_func=SyncApiStartrailView.as_view('syncapi_v1_startrail_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrailvideo', view_func=SyncApiStartrailVideoView.as_view('syncapi_v1_startrail_video_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/rawimage', view_func=SyncApiRawImageView.as_view('syncapi_v1_rawimage_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/fitsimage', view_func=SyncApiFitsImageView.as_view('syncapi_v1_fitsimage_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/panoramaimage', view_func=SyncApiPanoramaImageView.as_view('syncapi_v1_panoramaimage_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/panoramavideo', view_func=SyncApiPanoramaVideoView.as_view('syncapi_v1_panorama_video_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/thumbnail', view_func=SyncApiThumbnailView.as_view('syncapi_v1_thumbnail_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])

