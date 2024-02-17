from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
#import socket
from datetime import datetime
import time
import json
from pprint import pformat  # noqa: F401
import logging


logger = logging.getLogger('indi_allsky')


API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
MAX_RETRIES = 3


class youtube_oauth2(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(youtube_oauth2, self).__init__(*args, **kwargs)

        self.client = None


    def connect(self, *args, **kwargs):
        super(youtube_oauth2, self).connect(*args, **kwargs)


        if not self.config.get('YOUTUBE', {}).get('ENABLE'):
            raise ConnectionFailure('Youtube uploads are not enabled')


        import google.oauth2.credentials
        import googleapiclient.discovery

        credentials_json = kwargs['credentials_json']


        credentials_dict = json.loads(credentials_json)
        credentials = google.oauth2.credentials.Credentials(**credentials_dict)

        self.client = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)


    def close(self):
        super(youtube_oauth2, self).close()


    def put(self, *args, **kwargs):
        super(youtube_oauth2, self).put(*args, **kwargs)

        from googleapiclient.http import MediaFileUpload

        local_file = kwargs['local_file']
        metadata = kwargs['metadata']


        title_tmpl = self.config.get('YOUTUBE', {}).get('TITLE_TEMPLATE', 'Allsky Timelapse - {day_date:%Y-%m-%d} - {timeofday}')
        description_tmpl = self.config.get('YOUTUBE', {}).get('DESCRIPTION_TEMPLATE', '')


        if metadata['night']:
            timeofday = 'Night'
        else:
            timeofday = 'Day'


        template_data = {
            'day_date'      : datetime.strptime(metadata['dayDate'], '%Y%m%d').date(),
            'timeofday'     : timeofday,
            'asset_label '  : metadata['asset_label'],
        }


        title = title_tmpl.format(**template_data)
        description = description_tmpl.format(**template_data)


        privacy_status = self.config.get('YOUTUBE', {}).get('PRIVACY_STATUS', 'private')
        tags = self.config.get('YOUTUBE', {}).get('TAGS', [])
        category = self.config.get('YOUTUBE', {}).get('CATEGORY', 22)

        local_file_p = Path(local_file)


        body = {
            'snippet' : {
                'title'       : title,
                'description' : description,
                'tags'        : tags,
                'categoryId'  : category,
            },
            'status' : {
                'privacyStatus' : privacy_status
            }
        }

        insert_request = self.client.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=MediaFileUpload(
                str(local_file_p), chunksize=-1, resumable=True)
        )


        start = time.time()

        response = self.resumable_upload(insert_request)

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


        return response


    def resumable_upload(self, insert_request):
        from googleapiclient.errors import HttpError
        import httplib2

        retriable_exceptions = (httplib2.HttpLib2Error)

        response = None
        error = None
        retry = 0

        while response is None:
            try:
                logger.info("Uploading file...")
                status, response = insert_request.next_chunk()
                if response is not None:
                    if 'id' in response:
                        logger.info('Video id "%s" was successfully uploaded.', response['id'])
                        #logger.info('Response %s', pformat(response))
                        return response
                    else:
                        raise Exception('The upload failed with an unexpected response: {0:s}'.format(response))
            except HttpError as e:
                if e.resp.status in RETRIABLE_STATUS_CODES:
                    error = 'A retriable HTTP error {0} occurred:\n{1}'.format(e.resp.status, e.content)
                else:
                    raise
            except retriable_exceptions as e:
                error = 'A retriable error occurred: {0}'.format(str(e))

            if error is not None:
                logger.error(error)
                retry += 1
                if retry > MAX_RETRIES:
                    raise Exception('No longer attempting to retry.')

                logger.warning('Sleeping 2 seconds and then retrying...')
                time.sleep(2.0)
