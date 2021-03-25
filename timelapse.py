#!/usr/bin/env python

import sys
import time
import logging
from datetime import datetime
import copy
import functools

import ephem

from multiprocessing import Process
from multiprocessing import Queue
from multiprocessing import Value
from multiprocessing import current_process
from multiprocessing import log_to_stderr

import PyIndi
from astropy.io import fits
import cv2
import numpy

#import PythonMagick

#CCD_NAME       = "CCD Simulator"
#CCD_NAME       = "ZWO CCD ASI290MM"
CCD_NAME       = "SVBONY SV305 0"

EXPOSURE_PERIOD     = 15.10000   # time between beginning of each frame

CCD_GAIN_DAY    = 0
CCD_GAIN_NIGHT  = 250

CCD_PROPERTIES = {
    'CCD_BINNING' : 1,
    'CCD_GAIN'    : CCD_GAIN_NIGHT,
    'CCD_WBR'     : 95,
    'CCD_WBG'     : 65,
    'CCD_WBB'     : 110,
    'CCD_GAMMA'   : 65,
}

CCD_SWITCHES = {
    'FRAME_FORMAT' : [
        PyIndi.ISS_OFF,  # RAW12
        PyIndi.ISS_ON,   # RAW8
    ]
}


CCD_EXPOSURE_MAX    = 15.000000
CCD_EXPOSURE_MIN    =  0.000029
#CCD_EXPOSURE_DEF    =  1.000000
CCD_EXPOSURE_DEF    =  0.000100

TARGET_MEAN         = 50
TARGET_MEAN_MAX     = TARGET_MEAN + 5
TARGET_MEAN_MIN     = TARGET_MEAN - 5

LOCATION_LATITUDE  = '33'
LOCATION_LONGITUDE = '-84'
NIGHT_SUN_ALT = -15

FONT_FACE = cv2.FONT_HERSHEY_SIMPLEX
FONT_HEIGHT = 30
FONT_X = 15
FONT_Y = 30
FONT_COLOR = (200, 200, 200)
FONT_AA = cv2.LINE_AA
FONT_SCALE = 1 * 0.80
FONT_THICKNESS= 1


logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

logger = log_to_stderr()
logger.setLevel(logging.INFO)


class IndiClient(PyIndi.BaseClient):
 
    def __init__(self, img_q, exposure_v, sensortemp_v):
        super(IndiClient, self).__init__()

        self.img_q = img_q
        self.exposure_v = exposure_v
        self.sensortemp_v = sensortemp_v

        self.device = None
        self.logger = logging.getLogger('PyQtIndi.IndiClient')
        self.logger.info('creating an instance of PyQtIndi.IndiClient')


    def newDevice(self, d):
        self.logger.info("new device %s", d.getDeviceName())
        if d.getDeviceName() == CCD_NAME:
            self.logger.info("Set new device %s!", CCD_NAME)
            # save reference to the device in member variable
            self.device = d


    def newProperty(self, p):
        pName = p.getName()
        pDeviceName = p.getDeviceName()

        self.logger.info("new property %s for device %s", pName, pDeviceName)
        if self.device is not None and pName == "CONNECTION" and pDeviceName == self.device.getDeviceName():
            self.logger.info("Got property CONNECTION for %s!", CCD_NAME)
            # connect to device
            self.logger.info('Connect to device')
            self.connectDevice(self.device.getDeviceName())

            # set BLOB mode to BLOB_ALSO
            self.logger.info('Set BLOB mode')
            self.setBLOBMode(1, self.device.getDeviceName(), None)



    def removeProperty(self, p):
        self.logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        self.logger.info("new BLOB %s", bp.name)
        ### get image data
        imgdata = bp.getblobdata()

        ### process data in worker
        self.img_q.put(imgdata)

        #sleeptime = float(EXPOSURE_PERIOD) - float(self.exposure_v.value)
        #self.logger.info('...Sleeping for %0.6f s...', sleeptime)
        #time.sleep(sleeptime)



    def newSwitch(self, svp):
        self.logger.info ("new Switch %s for device %s", svp.name, svp.device)


    def newNumber(self, nvp):
        #self.logger.info("new Number %s for device %s", nvp.name, nvp.device)
        pass


    def newText(self, tvp):
        self.logger.info("new Text %s for device %s", tvp.name, tvp.device)


    def newLight(self, lvp):
        self.logger.info("new Light "+ lvp.name + " for device "+ lvp.device)


    def newMessage(self, d, m):
        #self.logger.info("new Message %s", d.messageQueue(m))
        pass


    def serverConnected(self):
        print("Server connected ({0}:{1})".format(self.getHost(), self.getPort()))


    def serverDisconnected(self, code):
        self.logger.info("Server disconnected (exit code = %d, %s, %d", code, str(self.getHost()), self.getPort())


    def takeExposure(self):
        self.logger.info("Taking %0.6f s exposure", float(self.exposure_v.value))
        #get current exposure time
        exp = self.device.getNumber("CCD_EXPOSURE")
        # set exposure time to 5 seconds
        exp[0].value = float(self.exposure_v.value)
        # send new exposure time to server/device
        self.sendNewNumber(exp)




class ImageProcessorWorker(Process):
    def __init__(self, img_q, exposure_v, gain_v, sensortemp_v):
        super(ImageProcessorWorker, self).__init__()

        self.img_q = img_q
        self.exposure_v = exposure_v
        self.gain_v = gain_v
        self.sensortemp_v = sensortemp_v

        self.hist_mean = []

        #self.dark = fits.open('dark_7s.fit')
        self.dark = None

        self.name = current_process().name


    def run(self):
        while True:
            imgdata = self.img_q.get()

            if not imgdata:
                return


            import io

            ### OpenCV ###
            blobfile = io.BytesIO(imgdata)
            hdulist = fits.open(blobfile)
            scidata_uncalibrated = hdulist[0].data

            #self.write_fit(hdulist)

            scidata_calibrated = self.calibrate(scidata_uncalibrated)
            scidata_color = self.colorize(scidata_calibrated)
            self.image_text(scidata_color)
            self.write_jpg(scidata_color)

            self.calculate_exposure(scidata_color)


    def write_fit(self, hdulist):
        now_str = datetime.now().strftime('%y%m%d_%H%M%S')

        hdulist.writeto("{0}.fit".format(now_str))

        logger.info('Finished writing fit file')


    def write_jpg(self, scidata):
        now_str = datetime.now().strftime('%y%m%d_%H%M%S')

        #cv2.imwrite("{0}_wb.jpg".format(now_str), scidata, [cv2.IMWRITE_JPEG_QUALITY, 90])
        #cv2.imwrite("{0}_rgb.png".format(now_str), scidata, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        cv2.imwrite("{0}_wb.png".format(now_str), scidata, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        #cv2.imwrite("{0}_rgb.tif".format(now_str), scidata)


        ### ImageMagick ###
        ### write image data to BytesIO buffer
        #blobfile = io.BytesIO(self.imgdata)

        #with open("frame.fit", "wb") as f:
        #    f.write(blobfile.getvalue())

        #i = PythonMagick.Image("frame.fit")
        #i.magick('TIF')
        #i.write('frame.tif')

        logger.info('Finished writing files')


    def calibrate(self, scidata_uncalibrated):

        if not self.dark:
            return scidata_uncalibrated

        scidata = cv2.subtract(scidata_uncalibrated, self.dark[0].data)
        return scidata



    def colorize(self, scidata):

        ###
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_BG2RGB)
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_RG2RGB)
        ###

        ###
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BayerGR2RGB)
        scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_GR2RGB)
        ###

        #scidata_rgb = self._convert_GRBG_to_RGB_8bit(scidata)

        #scidata_wb = self.white_balance(scidata_rgb)
        #scidata_wb = self.white_balance2(scidata_rgb)
        #scidata_wb = self.white_balance3(scidata_rgb)
        #scidata_wb = self.histogram_equalization(scidata_rgb)
        scidata_wb = scidata_rgb


        #if self.roi is not None:
        #    scidata = scidata[self.roi[1]:self.roi[1]+self.roi[3], self.roi[0]:self.roi[0]+self.roi[2]]
        #hdulist[0].data = scidata

        return scidata_wb


    def image_text(self, data_bytes):
        #cv2.rectangle(
        #    img=data_bytes,
        #    pt1=(0, 0),
        #    pt2=(350, 125),
        #    color=(0, 0, 0),
        #    thickness=cv2.FILLED,
        #)

        cv2.putText(
            img=data_bytes,
            text=datetime.now().strftime('%Y%m%d %H:%M:%S'),
            org=(FONT_X, FONT_Y),
            fontFace=FONT_FACE,
            color=FONT_COLOR,
            lineType=FONT_AA,
            fontScale=FONT_SCALE,
            thickness=FONT_THICKNESS,
        )

        cv2.putText(
            img=data_bytes,
            text='Exposure {0:0.6f}'.format(self.exposure_v.value),
            org=(FONT_X, FONT_Y + (FONT_HEIGHT * 1)),
            fontFace=FONT_FACE,
            color=FONT_COLOR,
            lineType=FONT_AA,
            fontScale=FONT_SCALE,
            thickness=FONT_THICKNESS,
        )

        cv2.putText(
            img=data_bytes,
            text='Gain {0:d}'.format(self.gain_v.value),
            org=(FONT_X, FONT_Y + (FONT_HEIGHT * 2)),
            fontFace=FONT_FACE,
            color=FONT_COLOR,
            lineType=FONT_AA,
            fontScale=FONT_SCALE,
            thickness=FONT_THICKNESS,
        )


    def calculate_exposure(self, data_bytes):
        r, g, b = cv2.split(data_bytes)
        r_avg = cv2.mean(r)[0]
        g_avg = cv2.mean(g)[0]
        b_avg = cv2.mean(b)[0]

        logger.info('R mean: %0.2f', r_avg)
        logger.info('G mean: %0.2f', g_avg)
        logger.info('B mean: %0.2f', b_avg)

         # Find the gain of each channel
        k = (r_avg + g_avg + b_avg) / 3

        logger.info('RGB average: %0.2f', k)


        self.hist_mean.insert(0, k)
        self.hist_mean = self.hist_mean[:3]  # only need last 3 values

        k_moving_average = functools.reduce(lambda a, b: a + b, self.hist_mean) / len(self.hist_mean)
        logger.info('Moving average: %0.2f', k_moving_average)


        current_exposure = self.exposure_v.value

        # Scale the exposure up and down based on targets
        if k_moving_average > TARGET_MEAN_MAX:
            #new_exposure = current_exposure / 2.0
            new_exposure = current_exposure / (( k_moving_average / float(TARGET_MEAN) ) * 0.75)

        elif k_moving_average < TARGET_MEAN_MIN:
            #new_exposure = current_exposure + 1
            new_exposure = current_exposure * (( float(TARGET_MEAN) / k_moving_average ) * 0.75)
        else:
            new_exposure = current_exposure



        # Do not exceed the limits
        if new_exposure < CCD_EXPOSURE_MIN:
            new_exposure = CCD_EXPOSURE_MIN
        elif new_exposure > CCD_EXPOSURE_MAX:
            new_exposure = CCD_EXPOSURE_MAX


        logger.warning('New calculated exposure: %0.6f', new_exposure)
        self.exposure_v.value = new_exposure


    def white_balance3(self, data_bytes):
        ### ohhhh, contrasty
        lab = cv2.cvtColor(data_bytes, cv2.COLOR_RGB2LAB)

        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        new_lab = cv2.merge((cl, a, b))

        new_data = cv2.cvtColor(new_lab, cv2.COLOR_LAB2RGB)
        return new_data


    def white_balance2(self, data_bytes):
        ### This seems to work
        r, g, b = cv2.split(data_bytes)
        r_avg = cv2.mean(r)[0]
        g_avg = cv2.mean(g)[0]
        b_avg = cv2.mean(b)[0]

         # Find the gain of each channel
        k = (r_avg + g_avg + b_avg) / 3
        kr = k / r_avg
        kg = k / g_avg
        kb = k / b_avg

        r = cv2.addWeighted(src1=r, alpha=kr, src2=0, beta=0, gamma=0)
        g = cv2.addWeighted(src1=g, alpha=kg, src2=0, beta=0, gamma=0)
        b = cv2.addWeighted(src1=b, alpha=kb, src2=0, beta=0, gamma=0)

        balance_img = cv2.merge([b, g, r])
        return balance_img


    def white_balance(self, data_bytes):
        ### This method does not work very well
        result = cv2.cvtColor(data_bytes, cv2.COLOR_RGB2LAB)
        avg_a = numpy.average(result[:, :, 1])
        avg_b = numpy.average(result[:, :, 2])
        result[:, :, 1] = result[:, :, 1] - ((avg_a - 128) * (result[:, :, 0] / 255.0) * 1.1)
        result[:, :, 2] = result[:, :, 2] - ((avg_b - 128) * (result[:, :, 0] / 255.0) * 1.1)
        data = cv2.cvtColor(result, cv2.COLOR_LAB2RGB)
        return data


    def histogram_equalization(self, img_in):
        # segregate color streams
        b,g,r = cv2.split(img_in)
        h_b, bin_b = numpy.histogram(b.flatten(), 256, [0, 256])
        h_g, bin_g = numpy.histogram(g.flatten(), 256, [0, 256])
        h_r, bin_r = numpy.histogram(r.flatten(), 256, [0, 256])# calculate cdf
        cdf_b = numpy.cumsum(h_b)
        cdf_g = numpy.cumsum(h_g)
        cdf_r = numpy.cumsum(h_r)

        # mask all pixels with value=0 and replace it with mean of the pixel values
        cdf_m_b = numpy.ma.masked_equal(cdf_b,0)
        cdf_m_b = (cdf_m_b - cdf_m_b.min())*255/(cdf_m_b.max()-cdf_m_b.min())
        cdf_final_b = numpy.ma.filled(cdf_m_b,0).astype('uint8')

        cdf_m_g = numpy.ma.masked_equal(cdf_g,0)
        cdf_m_g = (cdf_m_g - cdf_m_g.min())*255/(cdf_m_g.max()-cdf_m_g.min())
        cdf_final_g = numpy.ma.filled(cdf_m_g,0).astype('uint8')
        cdf_m_r = numpy.ma.masked_equal(cdf_r,0)
        cdf_m_r = (cdf_m_r - cdf_m_r.min())*255/(cdf_m_r.max()-cdf_m_r.min())
        cdf_final_r = numpy.ma.filled(cdf_m_r,0).astype('uint8')

        # merge the images in the three channels
        img_b = cdf_final_b[b]
        img_g = cdf_final_g[g]
        img_r = cdf_final_r[r]

        img_out = cv2.merge((img_b, img_g, img_r))# validation
        equ_b = cv2.equalizeHist(b)
        equ_g = cv2.equalizeHist(g)
        equ_r = cv2.equalizeHist(r)
        equ = cv2.merge((equ_b, equ_g, equ_r))
        #print(equ)
        #cv2.imwrite('output_name.png', equ)return img_out

        return img_out


    def _convert_GRBG_to_RGB_8bit(self, data_bytes):
        data_bytes = numpy.frombuffer(data_bytes, dtype=numpy.uint8)
        even = data_bytes[0::2]
        odd = data_bytes[1::2]
        # Convert bayer16 to bayer8
        bayer8_image = (even >> 4) | (odd << 4)
        bayer8_image = bayer8_image.reshape((1080, 1920))
        # Use OpenCV to convert Bayer GRBG to RGB
        return cv2.cvtColor(bayer8_image, cv2.COLOR_BayerGR2RGB)



class IndiTimelapse(object):

    def __init__(self):
        self.img_q = Queue()
        self.exposure_v = Value('f', copy.copy(CCD_EXPOSURE_DEF))
        self.gain_v = Value('i', copy.copy(CCD_GAIN_NIGHT))
        self.sensortemp_v = Value('f', 0)

        self.night = True

        logger.info('Starting ImageProcessorWorker process')
        self.img_process = ImageProcessorWorker(self.img_q, self.exposure_v, self.gain_v, self.sensortemp_v)
        self.img_process.start()



    def main(self):
        # instantiate the client
        indiclient = IndiClient(self.img_q, self.exposure_v, self.sensortemp_v)

        # set roi
        #indiclient.roi = (270, 200, 700, 700) # region of interest for my allsky cam

        # set indi server localhost and port 7624
        indiclient.setServer("localhost", 7624)

        # connect to indi server
        print("Connecting to indiserver")
        if (not(indiclient.connectServer())):
             print("No indiserver running on {0}:{1} - Try to run".format(indiclient.getHost(), indiclient.getPort()))
             print("  indiserver indi_simulator_telescope indi_simulator_ccd")
             sys.exit(1)


        device = None
        while not device:
            device = indiclient.getDevice(CCD_NAME)
            time.sleep(0.5)

        logger.info('Connected to device')


        ### Configure CCD Properties
        for key in CCD_PROPERTIES.keys():

            # loop until the property is populated
            indiprop = None
            while not indiprop:
                indiprop = device.getNumber(key)
                time.sleep(0.5)

            logger.info('Setting property %s: %s', key, str(CCD_PROPERTIES[key]))
            indiprop[0].value = CCD_PROPERTIES[key]
            indiclient.sendNewNumber(indiprop)



        ### Configure CCD Switches
        for key in CCD_SWITCHES:

            # loop until the property is populated
            indiswitch = None
            while not indiswitch:
                indiswitch = device.getSwitch(key)
                time.sleep(0.5)


            logger.info('Setting switch %s', key)
            for i, value in enumerate(CCD_SWITCHES[key]):
                indiswitch[i].s = value
            indiclient.sendNewSwitch(indiswitch)


        # Sleep after configuration
        time.sleep(1.0)


        while True:
            temp = device.getNumber("CCD_TEMPERATURE")
            if temp:
                logger.info("Sensor temperature: %d", temp[0].value)
                self.sensortemp_v.value = temp[0].value


            is_night = self.is_night()
            #logger.info('self.night: %r', self.night)
            #logger.info('is night: %r', is_night)

            ### Change gain when we change between day and night
            if self.night != is_night:
                logger.warning('Change between night and day')
                self.night = is_night

                if is_night:
                    self.gain_v.value = CCD_GAIN_NIGHT
                else:
                    self.gain_v.value = CCD_GAIN_DAY


                prop_gain = None
                while not prop_gain:
                    prop_gain = device.getNumber('CCD_GAIN')
                    time.sleep(0.5)

                logger.info('Setting camera gain to %d', self.gain_v.value)
                prop_gain[0].value = self.gain_v.value
                indiclient.sendNewNumber(prop_gain)

                # Sleep after configuration
                time.sleep(1.0)


            indiclient.takeExposure()
            time.sleep(EXPOSURE_PERIOD)



    def is_night(self):
        obs = ephem.Observer()
        obs.lon = LOCATION_LONGITUDE
        obs.lat = LOCATION_LATITUDE
        obs.date = datetime.now()

        sun = ephem.Sun()
        sun.compute(obs)

        logger.info('Sun altitude: %0.2f', sun.alt)
        return sun.alt < 0



if __name__ == "__main__":
    IndiTimelapse().main()


