import time
import io
import cv2
import logging

logger = logging.getLogger('indi_allsky')


class IndiAllSkyImageOverlay(object):

    def __init__(self, config):
        self.config = config

        self.load_interval = self.config.get('IMAGE_OVERLAY', {}).get('LOAD_INTERVAL', 300)

        self.images_dict = {
            'a' : {
                'data'     : None,
                'url'      : self.config.get('IMAGE_OVERLAY', {}).get('A_URL', ''),
                'image_file_type' : self.config.get('IMAGE_OVERLAY', {}).get('A_IMAGE_FILE_TYPE', 'jpg'),
                'username' : self.config.get('IMAGE_OVERLAY', {}).get('A_USERNAME', ''),
                'password' : self.config.get('IMAGE_OVERLAY', {}).get('A_PASSWORD', ''),
                'width'    : self.config.get('IMAGE_OVERLAY', {}).get('A_WIDTH', 250),
                'height'   : self.config.get('IMAGE_OVERLAY', {}).get('A_HEIGHT', 250),
                'x'        : self.config.get('IMAGE_OVERLAY', {}).get('A_X', 300),
                'y'        : self.config.get('IMAGE_OVERLAY', {}).get('A_Y', -300),
            },
        }


        self.next_load_time = time.time()  # load immediately

        self._timeout = 10


    def apply(self, image_data):
        now_time = time.time()

        if now_time > self.next_load_time:
            self.next_load_time = now_time + self.load_interval
            self.load_image()


        image_height, image_width = image_data.shape[:2]

        for image_dict in self.images_dict.values():
            if isinstance(image_dict['data'], type(None)):
                logger.warning('No image data for image overlay')
                return


            overlay_height, overlay_width = image_dict['data'].shape[:2]

            # calculate coordinates
            if image_dict['y'] < 0:
                x = image_width + image_dict['x']
            else:
                x = image_dict['x']

            if image_dict['y'] < 0:
                y = image_height + image_dict['y']
            else:
                y = image_dict['y']


            # sanity check coordinates
            if y + overlay_height > image_height:
                y = image_height - overlay_height

            if x + overlay_width > image_width:
                x = image_width - overlay_width


            # add image overlay
            image_data[
                y:y + overlay_height,
                x:x + overlay_width,
            ] = image_dict['data']


    def load_image(self):
        import pycurl

        for image_dict in self.images_dict.values():
            client = pycurl.Curl()

            # deprecated: will be replaced by PROTOCOLS_STR
            client.setopt(pycurl.PROTOCOLS, pycurl.PROTO_HTTP | pycurl.PROTO_HTTPS | pycurl.PROTO_FILE)

            client.setopt(pycurl.CONNECTTIMEOUT, int(self._timeout))

            client.setopt(pycurl.HTTPHEADER, ['Accept: */*', 'Connection: Close'])

            client.setopt(pycurl.FOLLOWLOCATION, 1)

            client.setopt(pycurl.SSL_VERIFYPEER, False)  # trust verification
            client.setopt(pycurl.SSL_VERIFYHOST, False)  # host verfication


            # Inherit settings from filetransfer section
            if self.config['FILETRANSFER'].get('FORCE_IPV4'):
                client.setopt(pycurl.IPRESOLVE, pycurl.IPRESOLVE_V4)
            elif self.config['FILETRANSFER'].get('FORCE_IPV6'):
                client.setopt(pycurl.IPRESOLVE, pycurl.IPRESOLVE_V6)


            # Apply custom options from config
            libcurl_opts = self.config['FILETRANSFER'].get('LIBCURL_OPTIONS', {})
            for k, v in libcurl_opts.items():
                # Not catching any exceptions here
                # Options are validated in web config

                if k.startswith('#'):
                    # comment
                    continue

                if k.startswith('CURLOPT_'):
                    # remove CURLOPT_ prefix
                    k = k[8:]

                curlopt = getattr(pycurl, k)
                client.setopt(curlopt, v)


            if image_dict['username']:
                client.setopt(pycurl.USERPWD, '{0:s}:{1:s}'.format(image_dict['username'], image_dict['password']))
                client.setopt(pycurl.HTTPAUTH, pycurl.HTTPAUTH_ANY)


            logger.info('Image Overlay URL: %s', image_dict['url'])

            client.setopt(pycurl.URL, image_dict['url'])


            f_image = io.BytesIO()
            client.setopt(pycurl.WRITEDATA, f_image)


            try:
                client.perform()
            except pycurl.error as e:
                rc, msg = e.args

                if rc in [pycurl.E_LOGIN_DENIED]:
                    logger.error('Authentication failed')
                elif rc in [pycurl.E_COULDNT_RESOLVE_HOST]:
                    logger.error('Hostname resolution failed')
                elif rc in [pycurl.E_COULDNT_CONNECT]:
                    logger.error('Connection failed')
                elif rc in [pycurl.E_OPERATION_TIMEDOUT]:
                    logger.error('Connection timed out')
                elif rc in [pycurl.E_URL_MALFORMAT]:
                    logger.error('Malformed URL')
                elif rc in [pycurl.E_UNSUPPORTED_PROTOCOL]:
                    logger.error('Unsupported protocol')
                else:
                    logger.error('pycurl error code: %d', rc)

                client.close()

                f_image.close()
                self.dl_file_p.unlink()
                return


            http_error = client.getinfo(pycurl.RESPONSE_CODE)
            if http_error >= 400:
                logger.info('HTTP return code: %d', http_error)
                self.dl_file_p.unlink()


            client.close()


            f_image.seek(0)  # rewind file
            if image_dict['image_file_type'] in ('jpg',):
                import simplejpeg

                try:
                    image_data = simplejpeg.decode_jpeg(f_image.read(), colorspace='BGR')
                except ValueError as e:
                    logger.error('Failed to decode image file: %s', str(e))
                    f_image.close()
                    return
            else:
                # use opencv for everything else
                image_data = cv2.imdecode(f_image, cv2.IMREAD_UNCHANGED)

                if isinstance(image_data, type(None)):
                    logger.error('Failed to decode image file')
                    f_image.close()
                    return


            f_image.close()


            image_data = cv2.resize(image_data, (image_dict['width'], image_dict['height']), interpolation=cv2.INTER_AREA)


            # update the image data
            image_dict['data'] = image_data

