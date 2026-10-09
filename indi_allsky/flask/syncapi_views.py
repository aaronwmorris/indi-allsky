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
from uuid import UUID


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


    def dispatch_request(self, lookup=False):
        try:
            #time.sleep(10)  # testing
            self.authorize(request.files['metadata'].stream.read())  # authenticate the request
        except AuthenticationFailure as e:
            app.logger.error('Authentication failure: %s', str(e))
            return jsonify({'error' : 'authentication failed'}), 400


        try:
            # Only the POST-only /lookup routes set this routing argument.
            # Authentication is shared; lookup requests never reach upload handlers.
            if lookup:
                return self.lookup()
            if request.method == 'POST':
                return self.post()
            elif request.method == 'PUT':
                return self.put()
            elif request.method == 'DELETE':
                return self.delete()
            elif request.method == 'GET':
                return self.get()
            else:
                app.logger.error('Invalid method: %s', str(request.method))
                return jsonify({}), 400

        except InvalidMetadata as e:
            app.logger.warning('Invalid SyncAPI metadata: %s', str(e))
            return jsonify({'error': 'invalid metadata'}), 400


    def post(self, overwrite=False):
        metadata = self.saveMetadata(request.files['metadata'])
        tmp_media_file_p = self.saveMedia(request.files['media'])
        try:
            media_file_size = tmp_media_file_p.stat().st_size
            if media_file_size != metadata.get('file_size', -1):
                # Authentication already succeeded. Reject damaged media without
                # misreporting a valid account/API key as an authentication failure.
                app.logger.error('Media file size does not match: expected %s bytes, received %d bytes', metadata.get('file_size'), media_file_size)
                return jsonify({'error': 'media_size_mismatch'}), 400
            try:
                camera = self.getCamera(metadata)
            except NoResultFound:
                app.logger.error('Camera not found: %s', metadata['camera_uuid'])
                return jsonify({'error': 'camera not found'}), 400
            file_entry = self.processPost(camera, metadata, tmp_media_file_p, overwrite=overwrite)
        except EntryExists as e:
            app.logger.error('Transfer skipped: %s', str(e))
            return jsonify({'error' : 'file_exists'}), 400
        finally:
            # Rejected paths and failed copies must not accumulate temp files.
            tmp_media_file_p.unlink(missing_ok=True)

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
        except EntryMissing as e:
            app.logger.error('Transfer failed: %s', str(e))
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
        except EntryMissing as e:
            app.logger.error('Transfer failed: %s', str(e))
            return jsonify({'error' : 'file_missing'}), 400

        return jsonify({
            'id'   : file_entry.id,
            'url'  : str(file_entry.getUrl(local=True)),
        })


    def lookup(self):
        if self.model == IndiAllSkyDbCameraTable:
            return self.get()

        metadata = self.saveMetadata(request.files['metadata'])
        camera_uuid = self.validateUuid(metadata.get('camera_uuid'))
        try:
            # Unlike getCamera(), a lookup must not update the camera's timezone.
            camera = IndiAllSkyDbCameraTable.query.filter_by(uuid=camera_uuid).one()
        except NoResultFound:
            return jsonify({'error': 'camera not found'}), 400
        return self.lookupSource(metadata, camera)


    def lookupSource(self, metadata, camera):
        """Check a pending source file without transferring its media payload."""
        try:
            expected_size = metadata['expected_size']
            expected_hash = metadata['sha256']
            if type(expected_size) is not int or expected_size <= 0 or not isinstance(expected_hash, str) or len(expected_hash) != 64:
                raise ValueError()
            if any(c not in '0123456789abcdefABCDEF' for c in expected_hash):
                raise ValueError()
            query = self.model.query.filter(self.model.camera_id == camera.id)
            if self.model == IndiAllSkyDbThumbnailTable:
                query = query.filter(self.model.uuid == self.validateUuid(metadata.get('uuid')))
            else:
                for field in ('createDate', 'utc_offset'):
                    if type(metadata[field]) not in (int, float) or not math.isfinite(metadata[field]):
                        raise ValueError()
                offset = metadata['utc_offset'] - datetime.now().astimezone().utcoffset().total_seconds()
                created = self.receiverDate(metadata['createDate'] + offset)
                query = query.filter(self.model.createDate == created)
            entry = query.first()
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return jsonify({'error': 'invalid source lookup'}), 400
        result = {'lookup_supported': True, 'present': False}
        # Only acknowledge a complete match. Missing/corrupt files and changed
        # thumbnail references must follow the normal upload/repair path.
        if entry and entry.thumbnail_uuid == metadata.get('thumbnail_uuid'):
            path = self.safePath(entry.getFilesystemPath())
            try:
                if path.stat().st_size == expected_size:
                    digest = hashlib.sha256()
                    with path.open('rb') as source:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            digest.update(block)
                    if digest.hexdigest() == expected_hash:
                        result.update(present=True, id=entry.id)
            except FileNotFoundError:
                pass
        return jsonify(result)


    def receiverDate(self, timestamp):
        # The model's MySQL/MariaDB DATETIME columns have second precision.
        # Match the stored value when recovering an interrupted upload.
        if db.engine.dialect.name in ('mysql', 'mariadb'):
            timestamp = math.floor(timestamp)
        return datetime.fromtimestamp(timestamp)


    def processPost(self, camera, metadata, tmp_file_p, overwrite=False):
        # offset createDate to account for difference between local and remote sites
        metadata['createDate'] += (metadata['utc_offset'] - datetime.now().astimezone().utcoffset().total_seconds())

        d_dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()

        date_folder = self.safePath(self.image_dir.joinpath('ccd_{0:s}'.format(camera.uuid), d_dayDate.strftime('%Y%m%d')))
        if not date_folder.exists():
            date_folder.mkdir(mode=0o755, parents=True)


        if metadata['night']:
            timeofday_str = 'night'
        else:
            timeofday_str = 'day'

        filename_p = self.safePath(date_folder.joinpath(
            self.filename_t.format(
                camera.id,
                d_dayDate.strftime('%Y%m%d'),
                timeofday_str,
                int(metadata['createDate']),
                tmp_file_p.suffix,  # suffix includes dot
            )
        ))

        try:
            # Several mini timelapses may belong to the same day/night period.
            identity = [self.model.dayDate == d_dayDate, self.model.night == bool(metadata['night'])]
            if self.model == IndiAllSkyDbMiniVideoTable:
                identity.append(self.model.createDate == self.receiverDate(metadata['createDate']))
            # delete old entry if it exists
            old_entry = self.model.query\
                .join(self.model.camera)\
                .filter(
                    and_(
                        IndiAllSkyDbCameraTable.id == camera.id,
                        *identity,
                    )
                )\
                .one()


            if not overwrite:
                raise EntryExists('Entry Exists: {0:s}'.format(old_entry.filename))


            self.validateAssetPath(old_entry)
            old_entry.deleteAsset()

            db.session.delete(old_entry)
            db.session.commit()
        except MultipleResultsFound as e:
            # this should never happen
            raise EntryError('Multiple entries for the same dayDate and night') from e
        except NoResultFound:
            pass


        if filename_p.exists():
            app.logger.warning('Removing orphaned file: %s', filename_p)
            filename_p.unlink()


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


            self.safePath(entry.getFilesystemPath())
            entry.deleteFile()

            app.logger.warning('Deleting entry %d', entry.id)
            db.session.delete(entry)
            db.session.commit()
        except NoResultFound:
            raise EntryMissing('Entry Missing: {0:d}'.format(entry_id))


    def getEntry(self, metadata, camera):
        try:
            entry = self.model.query\
                .join(IndiAllSkyDbCameraTable)\
                .filter(IndiAllSkyDbCameraTable.id == camera.id)\
                .filter(self.model.id == metadata['id'])\
                .one()

        except NoResultFound:
            raise EntryMissing('Entry Missing: {0:d}'.format(metadata['id']))


        return entry


    def saveMetadata(self, metadata_file):
        metadata_file.seek(0)  # rewind file
        try:
            metadata_json = json.load(metadata_file)
        except (ValueError, RecursionError) as e:
            raise InvalidMetadata('Expected a JSON object') from e
        if not isinstance(metadata_json, dict):
            raise InvalidMetadata('Expected a JSON object')
        return metadata_json


    def validateUuid(self, value):
        # Camera and thumbnail identifiers become directory/file names.
        # Authentication does not make arbitrary path components safe.
        if not isinstance(value, str) or len(value) != 36:
            raise InvalidMetadata('Invalid UUID')
        try:
            UUID(value)
        except ValueError as e:
            raise InvalidMetadata('Invalid UUID') from e
        return value


    def safePath(self, path):
        # Resolve existing symlinks as well as '..' before touching the path.
        try:
            path.resolve().relative_to(self.image_dir.resolve())
        except (ValueError, OSError, RuntimeError) as e:
            raise InvalidMetadata('Media path is outside the image folder') from e
        return path


    def validateAssetPath(self, entry):
        # Replacing an asset also deletes its thumbnail. Check both before
        # allowing either deletion, including records made by older receivers.
        self.safePath(entry.getFilesystemPath())
        if entry.thumbnail_uuid:
            thumbnail = IndiAllSkyDbThumbnailTable.query.filter_by(uuid=entry.thumbnail_uuid).first()
            if thumbnail:
                self.safePath(thumbnail.getFilesystemPath())


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
            raise AuthenticationFailure('Missing Authorization header')

        try:
            bearer, user_hmac_hash = auth_header.split(' ')
        except ValueError:
            raise AuthenticationFailure('Malformed API key')


        try:
            username, received_hmac = user_hmac_hash.split(':')
        except ValueError:
            raise AuthenticationFailure('Malformed API key')


        # compare_digest's string arguments must be ASCII. Reject malformed
        # SHA3-512 signatures before comparison (and before looking up a user).
        if (bearer.lower() != 'bearer' or len(received_hmac) != 128
                or any(c not in '0123456789abcdef' for c in received_hmac)):
            raise AuthenticationFailure('Malformed API key')

        user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()


        if not user or not user.active or not user.apikey:
            raise AuthenticationFailure('Unknown, inactive or unconfigured user')


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
        camera_uuid = self.validateUuid(metadata.get('camera_uuid'))
        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.uuid == camera_uuid)\
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
        except EntryMissing as e:
            app.logger.error('Transfer failed: %s', str(e))
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
        self.validateUuid(metadata.get('camera_uuid'))
        if type(metadata.get('id')) is not int or not 0 <= metadata['id'] <= 2**63 - 1:
            raise InvalidMetadata('Invalid camera ID')
        try:
            entry = self.model.query\
                .filter(self.model.id == metadata['id'])\
                .filter(self.model.uuid == metadata['camera_uuid'])\
                .one()

        except NoResultFound:
            raise EntryMissing()


        return entry


    def processPost(self, camera_notUsed, metadata, file_notUsed, overwrite=True):
        self.validateUuid(metadata.get('uuid'))
        addFunction_method = getattr(self._miscDb, self.add_function)
        entry = addFunction_method(
            metadata,
        )

        app.logger.info('Updated camera: %s', entry.uuid)

        return entry


    def delete(self):
        app.logger.error('delete not implemented')
        return jsonify({'error' : 'not_implemented'}), 400


class SyncApiBaseImageView(SyncApiBaseView):
    decorators = []

    type_folder = None


    def processPost(self, camera, image_metadata, tmp_file_p, overwrite=False):
        # offset createDate to account for difference between local and remote sites
        image_metadata['createDate'] += (image_metadata['utc_offset'] - datetime.now().astimezone().utcoffset().total_seconds())

        camera_createDate = self.receiverDate(image_metadata['createDate'])
        folder = self.getImageFolder(camera_createDate, image_metadata['night'], camera)

        date_str = camera_createDate.strftime('%Y%m%d_%H%M%S')
        image_file_p = self.safePath(folder.joinpath(
            self.filename_t.format(
                camera.id,
                date_str,
                tmp_file_p.suffix,
            )
        ))


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
                raise EntryExists('Entry Exists: {0:s}'.format(old_entry.filename))


            app.logger.warning('Removing orphaned image entry')
            self.validateAssetPath(old_entry)
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


        day_folder = self.safePath(self.image_dir.joinpath(
            'ccd_{0:s}'.format(camera.uuid),
            self.type_folder,
            '{0:s}'.format(day_ref.strftime('%Y%m%d')),
            timeofday_str,
        ))

        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)


        hour_str = exp_date.strftime('%d_%H')

        hour_folder = self.safePath(day_folder.joinpath('{0:s}'.format(hour_str)))
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

        return super(SyncApiImageView, self).processPost(camera, image_metadata, tmp_file_p, overwrite=overwrite)


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
        self.validateUuid(thumbnail_metadata.get('uuid'))
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


        thumbnail_file_p = self.safePath(thumbnail_dir_p.joinpath(self.filename_t.format(thumbnail_metadata['uuid'], tmp_file_p.suffix)))  # suffix includes dot


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
                raise EntryExists('Entry Exists: {0:s}'.format(str(thumbnail_file_p)))

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


        app.logger.info('Uploaded thumbnail: %s', thumbnail_file_p)

        return new_entry


class InvalidMetadata(Exception):
    pass


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


# Separate lookup routes keep POST's existing upload semantics intact.
bp_syncapi_allsky.add_url_rule('/sync/v1/camera/lookup', view_func=SyncApiCameraView.as_view('syncapi_v1_camera_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/image/lookup', view_func=SyncApiImageView.as_view('syncapi_v1_image_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/video/lookup', view_func=SyncApiVideoView.as_view('syncapi_v1_video_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/minivideo/lookup', view_func=SyncApiMiniVideoView.as_view('syncapi_v1_min_video_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/keogram/lookup', view_func=SyncApiKeogramView.as_view('syncapi_v1_keogram_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrail/lookup', view_func=SyncApiStartrailView.as_view('syncapi_v1_startrail_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrailvideo/lookup', view_func=SyncApiStartrailVideoView.as_view('syncapi_v1_startrail_video_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/rawimage/lookup', view_func=SyncApiRawImageView.as_view('syncapi_v1_rawimage_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/fitsimage/lookup', view_func=SyncApiFitsImageView.as_view('syncapi_v1_fitsimage_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/panoramaimage/lookup', view_func=SyncApiPanoramaImageView.as_view('syncapi_v1_panoramaimage_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/panoramavideo/lookup', view_func=SyncApiPanoramaVideoView.as_view('syncapi_v1_panoramavideo_lookup_view'), defaults={'lookup': True}, methods=['POST'])
bp_syncapi_allsky.add_url_rule('/sync/v1/thumbnail/lookup', view_func=SyncApiThumbnailView.as_view('syncapi_v1_thumbnail_lookup_view'), defaults={'lookup': True}, methods=['POST'])
