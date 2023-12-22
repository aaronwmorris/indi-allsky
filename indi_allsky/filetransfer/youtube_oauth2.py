from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
#from .exceptions import ConnectionFailure
#from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
#import socket
import time
import json
import logging

import googleapiclient.discovery

logger = logging.getLogger('indi_allsky')


RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
MAX_RETRIES = 3


class youtube_oauth2(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(youtube_oauth2, self).__init__(*args, **kwargs)

        self.client = None


    def connect(self, *args, **kwargs):
        super(youtube_oauth2, self).connect(*args, **kwargs)

        import google.oauth2.credentials

        credentials_json = kwargs['credentials_json']


        credentials_dict = json.loads(credentials_json)
        credentials = google.oauth2.credentials.Credentials(**credentials_dict)

        self.client = googleapiclient.discovery.build(self.api_service_name, self.api_version, credentials=credentials)


    def close(self):
        super(youtube_oauth2, self).close()


    def put(self, *args, **kwargs):
        super(youtube_oauth2, self).put(*args, **kwargs)

        from googleapiclient.http import MediaFileUpload

        local_file = kwargs['local_file']
        privacy_status = kwargs['privacy_status']
        tags = kwargs['tags']
        category = kwargs['category']

        local_file_p = Path(local_file)


        body = {
            'snippet' : {
                'title'       : video_args.title,
                'description' : video_args.description,
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

        self.resumable_upload(insert_request)

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


    def resumable_upload(self, insert_request):
        from googleapiclient.errors import HttpError
        import httplib2

        retriable_exceptions = (httplib2.HttpLib2Error)

        response = None
        error = None
        retry = 0

        while response is None:
            try:
                print("Uploading file...")
                status, response = insert_request.next_chunk()
                if response is not None:
                    if 'id' in response:
                        print("Video id '%s' was successfully uploaded." % response['id'])
                        return response['id']
                    else:
                        raise Exception('The upload failed with an unexpected response: {0:s}'.format(response))
            except HttpError as e:
                if e.resp.status in RETRIABLE_STATUS_CODES:
                    error = f"A retriable HTTP error {e.resp.status} occurred:\n{e.content}"
                else:
                    raise
            except retriable_exceptions as e:
                error = 'A retriable error occurred: {0}'.format(str(e))

            if error is not None:
                print(error)
                retry += 1
                if retry > MAX_RETRIES:
                    raise Exception('No longer attempting to retry.')

                logger.error('Sleeping 2 seconds and then retrying...')
                time.sleep(2.0)
