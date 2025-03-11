import os
import cv2
from fractions import Fraction
import math
import numpy
from datetime import datetime
from datetime import timezone
#import PIL
from PIL import Image
import time
from pathlib import Path
import tempfile
import ephem
import logging

from .stars import IndiAllSkyStars


logger = logging.getLogger('indi_allsky')



class StarTrailGenerator(object):

    def __init__(self, config, bin_v, skip_frames=0, mask=None):
        self.config = config
        self.bin_v = bin_v
        self.skip_frames = skip_frames

        self.process_count = 0

        self._max_adu = 50
        self._mask_threshold = 190
        self._pixel_cutoff_threshold = 1.0

        self._min_stars = 0
        self._stars_detect = None  # instantiated later

        self._latitude = 0.0
        self._longitude = 0.0
        self._sun_alt_threshold = -15.0


        # these default settings disable thresholds
        self._moonmode_alt = 91.0
        self._moonmode_phase = 101.0
        self._moon_alt_threshold = 91.0
        self._moon_phase_threshold = 101.0


        self.original_height = None
        self.original_width = None

        self.trail_image = None
        self.pixels_cutoff = None
        self.excluded_images = {
            'adu'       : 0,
            'sun_alt'   : 0,
            'moon_mode' : 0,
            'moon_alt'  : 0,
            'stars'     : 0,
            'pixels'    : 0,
        }

        self.obs = ephem.Observer()
        self.sun = ephem.Sun()
        self.moon = ephem.Moon()


        # disable atmospheric refraction calcs
        self.obs.pressure = 0


        self.image_processing_elapsed_s = 0

        self._sqm_mask = mask

        # this is a default image that is used in case all images are excluded
        self.placeholder_image = None
        self.placeholder_adu = 255


        self._trail_count = 0
        self._timelapse_frame_count = 0
        self._timelapse_frame_list = list()


        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


        # setup a folder for scratch files which can be deleted if orphaned
        scratch_base_dir = self.image_dir.joinpath('scratch')
        if not scratch_base_dir.exists():
            scratch_base_dir.mkdir(parents=True)


        # this needs to be a class variable
        self.timelapse_tmpdir = tempfile.TemporaryDirectory(dir=scratch_base_dir, suffix='_startrail_timelapse')    # context manager automatically deletes files when finished
        self.timelapse_tmpdir_p = Path(self.timelapse_tmpdir.name)



    @property
    def max_adu(self):
        return self._max_adu

    @max_adu.setter
    def max_adu(self, new_max_adu):
        self._max_adu = int(new_max_adu)

    @property
    def mask_threshold(self):
        return self._mask_threshold

    @mask_threshold.setter
    def mask_threshold(self, new_thold):
        self._mask_threshold = int(new_thold)

    @property
    def pixel_cutoff_threshold(self):
        return self._pixel_cutoff_threshold

    @pixel_cutoff_threshold.setter
    def pixel_cutoff_threshold(self, new_thold):
        self._pixel_cutoff_threshold = float(new_thold)

    @property
    def min_stars(self):
        return self._min_stars

    @min_stars.setter
    def min_stars(self, new_min_stars):
        self._min_stars = int(new_min_stars)

    @property
    def trail_count(self):
        return self._trail_count

    @trail_count.setter
    def trail_count(self, new_trail_count):
        return  # read only

    @property
    def timelapse_frame_count(self):
        return self._timelapse_frame_count

    @timelapse_frame_count.setter
    def timelapse_frame_count(self, new_frame_count):
        return  # read only

    @property
    def timelapse_frame_list(self):
        return self._timelapse_frame_list

    @timelapse_frame_list.setter
    def timelapse_frame_list(self, new_frame_list):
        return  # read only

    @property
    def latitude(self):
        return self._latitude

    @latitude.setter
    def latitude(self, new_latitude):
        self._latitude = float(new_latitude)
        self.obs.lat = math.radians(self._latitude)

    @property
    def longitude(self):
        return self._longitude

    @longitude.setter
    def longitude(self, new_longitude):
        self._longitude = float(new_longitude)
        self.obs.lon = math.radians(self._longitude)

    @property
    def sun_alt_threshold(self):
        return self._sun_alt_threshold

    @sun_alt_threshold.setter
    def sun_alt_threshold(self, new_sun_alt_threshold):
        self._sun_alt_threshold = float(new_sun_alt_threshold)

    @property
    def moon_alt_threshold(self):
        return self._moon_alt_threshold

    @moon_alt_threshold.setter
    def moon_alt_threshold(self, new_moon_alt_threshold):
        self._moon_alt_threshold = float(new_moon_alt_threshold)

    @property
    def moon_phase_threshold(self):
        return self._moon_phase_threshold

    @moon_phase_threshold.setter
    def moon_phase_threshold(self, new_moon_phase_threshold):
        self._moon_phase_threshold = float(new_moon_phase_threshold)

    @property
    def moonmode_alt(self):
        return self._moonmode_alt

    @moonmode_alt.setter
    def moonmode_alt(self, new_moonmode_alt):
        self._moonmode_alt = float(new_moonmode_alt)

    @property
    def moonmode_phase(self):
        return self._moonmode_phase

    @moonmode_phase.setter
    def moonmode_phase(self, new_moonmode_phase):
        self._moonmode_phase = float(new_moonmode_phase)

    @property
    def shape(self):
        return self.trail_image.shape

    @shape.setter
    def shape(self, *args):
        pass  # read only



    ### To be removed
    #def generate(self, outfile, file_list):
    #    # Exclude empty files
    #    file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

    #    # Sort by timestamp
    #    file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


    #    processing_start = time.time()

    #    for file_p in file_list_ordered:
    #        logger.info('Reading file: %s', file_p)

    #        try:
    #            with Image.open(str(file_p)) as img:
    #                image = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)
    #        except PIL.UnidentifiedImageError:
    #            logger.error('Unable to read %s', file_p)
    #            continue


    #        self.processImage(file_p, image)


    #    self.finalize(outfile)


    #    processing_elapsed_s = time.time() - processing_start
    #    logger.warning('Total star trail processing in %0.1f s', processing_elapsed_s)


    def processImage(self, file_p, image, adu=None, star_count=None):
        self.process_count += 1

        if self.process_count <= self.skip_frames:
            return


        image_processing_start = time.time()

        image_height, image_width = image.shape[:2]


        if isinstance(self.trail_image, type(None)):
            # this only happens on the first image

            self.original_height = image_height
            self.original_width = image_width

            self.pixels_cutoff = (image_height * image_width) * (self.pixel_cutoff_threshold / 100)

            # base image is just a black image
            if len(image.shape) == 2:
                self.trail_image = numpy.zeros((image_height, image_width), dtype=numpy.uint8)
            else:
                self.trail_image = numpy.zeros((image_height, image_width, 3), dtype=numpy.uint8)


        if image_height != self.original_height or image_width != self.original_width:
            logger.error('Image with dimension mismatch: %s', file_p)
            return


        if isinstance(self._sqm_mask, type(None)):
            self._generateSqmMask(image)

        if isinstance(self._stars_detect, type(None)):
            self._stars_detect = IndiAllSkyStars(self.config, self.bin_v, mask=self._sqm_mask)


        # need grayscale image for mask generation
        if len(image.shape) == 2:
            image_gray = image.copy()
        else:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


        if isinstance(adu, type(None)):
            m_avg = cv2.mean(image_gray, mask=self._sqm_mask)[0]
        else:
            m_avg = adu


        if m_avg < self.placeholder_adu:
            # placeholder should be the image with the lowest calculated ADU
            self.placeholder_image = image
            self.placeholder_adu = m_avg


        mtime_datetime_utc = datetime.fromtimestamp(file_p.stat().st_mtime).astimezone(tz=timezone.utc)
        self.obs.date = mtime_datetime_utc

        self.sun.compute(self.obs)
        sun_alt = math.degrees(self.sun.alt)

        if sun_alt > self.sun_alt_threshold:
            #logger.warning(' Excluding image due to sun altitude: %0.1f', sun_alt)
            self.excluded_images['sun_alt'] += 1
            return


        self.moon.compute(self.obs)
        moon_alt = math.degrees(self.moon.alt)
        moon_phase = self.moon.moon_phase * 100.0


        if moon_alt > self.moonmode_alt and moon_phase > self.moonmode_phase:
            #logger.warning(' Excluding image due to moon mode: %0.1f/%0.1f%%', moon_alt, moon_phase)
            self.excluded_images['moon_mode'] += 1
            return

        if moon_alt > self.moon_alt_threshold and moon_phase > self.moon_phase_threshold:
            #logger.warning(' Excluding image due to moon altitude/phase: %0.1f/%0.1f%%', moon_alt, moon_phase)
            self.excluded_images['moon_alt'] += 1
            return


        if m_avg > self.max_adu:
            #logger.warning(' Excluding image due to brightness: %0.2f', m_avg)
            self.excluded_images['adu'] += 1
            return

        #logger.info(' Image brightness: %0.2f', m_avg)

        pixels_above_cutoff = (image_gray > self.mask_threshold).sum()
        if pixels_above_cutoff > self.pixels_cutoff:
            #logger.warning(' Excluding image due to pixel cutoff: %d', pixels_above_cutoff)
            self.excluded_images['pixels'] += 1
            return

        self._trail_count += 1


        if self.min_stars > 0:
            if isinstance(star_count, type(None)):
                star_count = len(self._stars_detect.detectObjects(image_gray))

            if star_count < self.min_stars:
                #logger.warning(' Excluding image due to stars: %d', star_count)
                self.excluded_images['stars'] += 1
                return


        ### Here is the magic
        self.trail_image = cv2.max(self.trail_image, image)


        # Star trail timelapse processing
        if self.config.get('STARTRAILS_TIMELAPSE', True):
            image_mtime = file_p.stat().st_mtime

            f_tmp_frame = tempfile.NamedTemporaryFile(dir=self.timelapse_tmpdir_p, suffix='.{0:s}'.format(self.config['IMAGE_FILE_TYPE']), delete=False)
            f_tmp_frame.close()

            f_tmp_frame_p = Path(f_tmp_frame.name)

            if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
                img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
                img_rgb.save(str(f_tmp_frame_p), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'])
            elif self.config['IMAGE_FILE_TYPE'] in ('png',):
                #img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
                #img_rgb.save(str(f_tmp_frame_p), compress_level=self.config['IMAGE_FILE_COMPRESSION']['png'])

                # opencv is faster than Pillow with PNG
                cv2.imwrite(str(f_tmp_frame_p), self.trail_image, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
            elif self.config['IMAGE_FILE_TYPE'] in ('webp',):
                img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
                img_rgb.save(str(f_tmp_frame_p), quality=90, lossless=False)
            elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
                img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
                img_rgb.save(str(f_tmp_frame_p), compression='tiff_lzw')
            else:
                raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

            # put original mtime on file
            os.utime(f_tmp_frame_p, times=(image_mtime, image_mtime))

            self._timelapse_frame_list.append(f_tmp_frame_p)
            self._timelapse_frame_count += 1


        self.image_processing_elapsed_s += time.time() - image_processing_start


    def finalize(self, outfile, camera):
        import piexif

        outfile_p = Path(outfile)

        logger.info('Star trails images processed in %0.1f s', self.image_processing_elapsed_s)
        logger.info(
            'Excluded %d images - adu: %d, sun alt: %d, moon mode: %d, moon alt: %d, stars: %d, pixels: %d',
            sum(self.excluded_images.values()),
            self.excluded_images['adu'],
            self.excluded_images['sun_alt'],
            self.excluded_images['moon_mode'],
            self.excluded_images['moon_alt'],
            self.excluded_images['stars'],
            self.excluded_images['pixels'],
        )


        if self.trail_count == 0:
            logger.warning('Not enough images found to build star trail, using placeholder image')
            self.trail_image = self.placeholder_image


        ### EXIF tags ###
        exp_date_utc = datetime.now(tz=timezone.utc)

        # Python 3.6, 3.7 does not support as_integer_ratio()
        focal_length_frac = Fraction(camera.lensFocalLength).limit_denominator()
        focal_length = (focal_length_frac.numerator, focal_length_frac.denominator)

        f_number_frac = Fraction(camera.lensFocalRatio).limit_denominator()
        f_number = (f_number_frac.numerator, f_number_frac.denominator)

        zeroth_ifd = {
            piexif.ImageIFD.Model            : camera.name,
            piexif.ImageIFD.Software         : 'indi-allsky',
        }
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal  : exp_date_utc.strftime('%Y:%m:%d %H:%M:%S'),
            piexif.ExifIFD.LensModel         : camera.lensName,
            piexif.ExifIFD.LensSpecification : (focal_length, focal_length, f_number, f_number),
            piexif.ExifIFD.FocalLength       : focal_length,
            piexif.ExifIFD.FNumber           : f_number,
        }


        jpeg_exif_dict = {
            '0th'   : zeroth_ifd,
            'Exif'  : exif_ifd,
        }


        if not self.config.get('IMAGE_EXIF_PRIVACY'):
            if camera.owner:
                zeroth_ifd[piexif.ImageIFD.Copyright] = camera.owner


            long_deg, long_min, long_sec = self.decdeg2dms(camera.longitude)
            lat_deg, lat_min, lat_sec = self.decdeg2dms(camera.latitude)

            if long_deg < 0:
                long_ref = 'W'
            else:
                long_ref = 'E'

            if lat_deg < 0:
                lat_ref = 'S'
            else:
                lat_ref = 'N'

            gps_datestamp = exp_date_utc.strftime('%Y:%m:%d')
            gps_hour   = int(exp_date_utc.strftime('%H'))
            gps_minute = int(exp_date_utc.strftime('%M'))
            gps_second = int(exp_date_utc.strftime('%S'))

            gps_ifd = {
                piexif.GPSIFD.GPSVersionID       : (2, 2, 0, 0),
                piexif.GPSIFD.GPSDateStamp       : gps_datestamp,
                piexif.GPSIFD.GPSTimeStamp       : ((gps_hour, 1), (gps_minute, 1), (gps_second, 1)),
                piexif.GPSIFD.GPSLongitudeRef    : long_ref,
                piexif.GPSIFD.GPSLongitude       : ((int(abs(long_deg)), 1), (int(long_min), 1), (0, 1)),  # no seconds
                piexif.GPSIFD.GPSLatitudeRef     : lat_ref,
                piexif.GPSIFD.GPSLatitude        : ((int(abs(lat_deg)), 1), (int(lat_min), 1), (0, 1)),  # no seconds
            }

            jpeg_exif_dict['GPS'] = gps_ifd


        jpeg_exif = piexif.dump(jpeg_exif_dict)


        write_img_start = time.time()

        logger.warning('Creating star trail: %s', outfile_p)
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'], exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            #img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
            #img_rgb.save(str(outfile_p), compress_level=self.config['IMAGE_FILE_COMPRESSION']['png'])

            # opencv is faster than Pillow with PNG
            cv2.imwrite(str(outfile_p), self.trail_image, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('webp',):
            img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), quality=90, lossless=False, exif=jpeg_exif)
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), compression='tiff_lzw')
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])

        write_img_elapsed_s = time.time() - write_img_start
        logger.info('Image compressed in %0.4f s', write_img_elapsed_s)


        # set default permissions
        outfile_p.chmod(0o644)


    def decdeg2dms(self, dd):
        is_positive = dd >= 0
        dd = abs(dd)
        minutes, seconds = divmod(dd * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        degrees = degrees if is_positive else -degrees
        return degrees, minutes, seconds


    def _generateSqmMask(self, img):
        logger.info('Generating mask based on SQM_ROI')

        image_height, image_width = img.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        ### Not going to use the user defined SQM_ROI for now
        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1 = int(sqm_roi[0] / self.bin_v.value)
            y1 = int(sqm_roi[1] / self.bin_v.value)
            x2 = int(sqm_roi[2] / self.bin_v.value)
            y2 = int(sqm_roi[3] / self.bin_v.value)
        except IndexError:
            logger.warning('Using central ROI for ADU mask')
            sqm_fov_div = self.config.get('SQM_FOV_DIV', 4)
            x1 = int((image_width / 2) - (image_width / sqm_fov_div))
            y1 = int((image_height / 2) - (image_height / sqm_fov_div))
            x2 = int((image_width / 2) + (image_width / sqm_fov_div))
            y2 = int((image_height / 2) + (image_height / sqm_fov_div))

        # The white area is what we keep
        cv2.rectangle(
            img=mask,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=(255),  # mono
            thickness=cv2.FILLED,
        )

        self._sqm_mask = mask

