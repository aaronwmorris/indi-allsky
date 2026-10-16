from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import CertificateValidationFailure
from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
import io
import time
import math
import socket
import ssl
import json
import hashlib
import hmac
import logging


requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


logger = logging.getLogger('indi_allsky')


class requests_syncapi_v1(GenericFileTransfer):

    time_skew = 300  # number of seconds the client is allowed to deviate from server


    def __init__(self, *args, **kwargs):
        super(requests_syncapi_v1, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 443
        self.url = None
        self.apikey = None
        self.quiet = kwargs.get('quiet', False)


    def connect(self, *args, **kwargs):
        super(requests_syncapi_v1, self).connect(*args, **kwargs)

        ### The full connect and transfer happens under the put() function

        endpoint_url = kwargs['hostname']
        self.username = kwargs['username']
        self.apikey = kwargs['apikey']
        cert_bypass = kwargs.get('cert_bypass')


        if cert_bypass:
            self.verify = False
        else:
            self.verify = True


        self.url = endpoint_url


        self.client = requests


        if cert_bypass:
            self.cert_bypass = True



    def close(self):
        super(requests_syncapi_v1, self).close()


    def put(self, *args, **kwargs):
        # Quiet archive logging is specific to SyncAPI, not other protocols.
        if self.quiet and not self.delete:
            logger.debug('Uploading %s', kwargs['local_file'])
        else:
            super(requests_syncapi_v1, self).put(*args, **kwargs)

        metadata = kwargs['metadata']
        local_file = kwargs['local_file']
        empty_file = kwargs['empty_file']


        #logger.info('requests URL: %s', self.url)

        # Lookups use the same signed multipart metadata as uploads, but do not
        # open/send the local media. Cameras also have no media payload.
        if kwargs.get('lookup') or str(local_file) == 'camera':
            local_file_p = Path('bogus.ext')
            local_file_size = 1024  # fake
            f_media = io.BytesIO(b'')  # no data
            metadata['file_size'] = 0
        else:
            # all other entry types
            local_file_p = Path(local_file)

            if not empty_file:
                local_file_size = local_file_p.stat().st_size
                metadata['file_size'] = local_file_size  # needed to validate
                f_media = io.open(str(local_file_p), 'rb')
            else:
                local_file_size = 1024  # fake
                f_media = io.BytesIO(b'')  # no data
                metadata['file_size'] = 0


        json_metadata = json.dumps(metadata)
        f_metadata = io.StringIO(json_metadata)


        fields = {
            'metadata' : (
                'metadata.json',
                f_metadata,
                'application/json',
            ),
            'media' : (
                local_file_p.name,  # need file extension from original file
                f_media,
                'application/octet-stream',
            ),
            # Werkzeug 3.1.6-3.1.8 can append a CR to the last part when the
            # closing delimiter crosses a parser read boundary. Keep both
            # signed metadata and media before an unused final form field.
            # This avoids relying on a particular boundary or read size.
            'syncapi_end': '',
        }


        mp_enc = MultipartEncoder(fields=fields)


        time_floor = math.floor(time.time() / self.time_skew)

        # data is received as bytes
        hmac_message = str(time_floor).encode() + json_metadata.encode()

        message_hmac = hmac.new(
            self.apikey.encode(),
            msg=hmac_message,
            digestmod=hashlib.sha3_512,
        ).hexdigest()


        headers = {
            'Authorization' : 'Bearer {0:s}:{1:s}'.format(self.username, message_hmac),
            'Connection'    : 'close',  # no need for keep alives
            'Content-Type'  : mp_enc.content_type,
        }


        start = time.time()

        try:
            # Archive runs opt into pacing/progress. Leave camera updates,
            # lookups and the original automatic-upload path unchanged.
            if metadata['file_size'] and (kwargs.get('upload_limit') or kwargs.get('progress_callback')):
                rate = kwargs.get('upload_limit', 0) * 1024
                if rate and mp_enc.len / rate > self.time_skew * 4:
                    raise TransferFailure('The upload speed limit would make "{0}" take more than 20 minutes, '
                                          'exceeding the receiver authentication window. Increase the speed limit '
                                          'and start synchronization again.'.format(local_file_p.name))
                previous_read = 0

                def monitor_upload(monitor):
                    nonlocal previous_read
                    # Pace each block before requests writes it to the socket.
                    # Charging all multipart bytes prevents short files or slow
                    # socket writes from accumulating credit for a later burst.
                    count = monitor.bytes_read - previous_read
                    previous_read = monitor.bytes_read
                    if rate and count:
                        kwargs.get('upload_wait', time.sleep)(count / rate)
                    if kwargs.get('progress_callback'):
                        kwargs['progress_callback'](f_media.tell(), metadata['file_size'])

                mp_enc = MultipartEncoderMonitor(mp_enc, monitor_upload)
            # POST lookup bodies pass through proxies that reject GET bodies.
            # Use a dedicated read-only route; POST on the upload route writes.
            request_method = self.client.post if kwargs.get('lookup') else self.client.put
            request_url = self.url.rstrip('/') + '/lookup' if kwargs.get('lookup') else self.url
            request_options = {'allow_redirects': False} if kwargs.get('lookup') else {}
            r = request_method(
                request_url,
                data=mp_enc,
                headers=headers,
                verify=self.verify,
                timeout=(self.connect_timeout, self.timeout),
                **request_options,
            )
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ConnectTimeout as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.SSLError as e:
            raise CertificateValidationFailure(str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ChunkedEncodingError as e:
            # A lost response is not proof that the upload failed. Archive
            # retries check the receiver's size/hash before sending it again.
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ReadTimeout as e:
            raise ConnectionFailure(str(e)) from e
        except ssl.SSLCertVerificationError as e:
            raise CertificateValidationFailure(str(e)) from e
        finally:
            f_metadata.close()
            f_media.close()


        # A receiver/proxy can restart between a successful probe and an upload.
        # Use the archive worker's bounded retries and lookup-before-resend path
        # for these responses too. Keep legacy automatic-upload handling intact.
        if (self.quiet or kwargs.get('availability_probe')) and r.status_code in (429, 500, 502, 503, 504):
            raise ConnectionFailure('Receiver is temporarily unavailable (HTTP {0:d}).'.format(r.status_code))

        if kwargs.get('availability_probe'):
            try:
                response = r.json()
            except ValueError:
                response = None
            if r.status_code in (401, 403):
                raise AuthenticationFailure('Receiver authentication failed')
            if isinstance(response, dict):
                if r.status_code == 200 and type(response.get('id')) is int and response['id'] > 0:
                    return response
                if r.status_code == 400 and response.get('error') == 'camera_missing':
                    return response
                if response.get('error') == 'authentication failed':
                    raise AuthenticationFailure('Receiver authentication failed')
            raise TransferFailure('Unexpected receiver readiness response (HTTP {0:d}).'.format(r.status_code))

        if r.status_code >= 400:
            try:
                error = r.json().get('error')
            except (ValueError, AttributeError):
                error = None
            if r.status_code == 400 and error == 'media_size_mismatch':
                raise TransferFailure('Receiver rejected "{0}": media size does not match the signed metadata. Check the receiver logs.'.format(local_file_p.name))
            if self.quiet:
                if r.status_code in (401, 403) or error == 'authentication failed':
                    raise AuthenticationFailure('Receiver authentication failed')
                if kwargs.get('lookup'):
                    raise TransferFailure('Receiver lookup failed (HTTP {0:d}). Update the receiver to a version supporting archive synchronization and check its logs.'.format(r.status_code))
                raise TransferFailure('Receiver rejected the transfer (HTTP {0:d}). Check its storage and service logs.'.format(r.status_code))
            raise TransferFailure('Sync error: {0:d}'.format(r.status_code))


        upload_elapsed_s = time.time() - start
        log = logger.debug if self.quiet else logger.info
        log('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / max(upload_elapsed_s, 0.000001) / 1024)


        try:
            return json.loads(r.text)
        except ValueError as e:
            raise TransferFailure('Receiver returned an invalid transfer acknowledgement.') from e

