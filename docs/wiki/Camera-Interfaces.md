# Overview
indi-allsky is designed to use the INDI library for interfacing with cameras.  This allows indi-allsky support more cameras than just about any other all sky project.

## INDI
INDI is the default camera interface.  The INDI interface connects to the configured INDI server and 

Key Settings:
1. INDI Server
1. INDI Port
1. INDI Camera Name - This setting should only be configured if you have multiple cameras available on the indiserver.  The name will be the name assigned by the indi library for the camera.  The default behavior is to connect to the first camera returned by the indiserver which should be the only camera in most cases.
1. INDI Camera Config - This is JSON data for configuring camera specific settings.  https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config

## libcamera
The libcamera interface utilizes the libcamera command-line interface rpicam-still or libcamera-still to interface with CSI/MIPI connected cameras such as the Raspberry PI HQ Camera.  The libcamera interface supports RAW image capture via the DNG file format.  You may also utilize JPEG capture and the AWB features of libcamera.

## MQTT - libcamera
This interface allows you to control exposures on a remote Raspberry Pi with a CSI/MIPI camera via MQTT.  The script `./misc/mqtt_remote_libcamera.py` can be installed on the remote Raspberry Pi and listens for exposure requests on an MQTT topic.  Once the exposure is completed, the image and metadata are sent back on a different MQTT topic for indi-allsky to process.

* `MQTT_HOSTNAME=hostname MQTT_USERNAME=username MQTT_PASSWORD=password ./misc/mqtt_remote_libcamera.py`

Key Settings:
* AWB: libcamera AWB performs white balancing in camera.  libcamera takes multiple exposures and returns the best result.  The lag of the multiple exposures is not noticeable a low exposures during the day, but at night, a 15 second exposure might take 1 minute or more to complete.
* DNG RAW mode - indi-allsky processes the DNG RAW data by default, but you may revert to JPEG mode.  DNG mode is recommended if you want to take Dark frames.

## pyCurl Camera
The pyCurl camera was designed to interface with common Network IP Web Cameras like security cameras.  The pyCurl interface downloads a JPEG or PNG image from the web server running on the IP Web Camera.  The IP Web Camera exposure and gain are managed by the camera itself and not by indi-allsky.

## INDI Accumulator
The Accumulator camera is a special type of interface for creating synthetic images from multiple sub-exposures.  For instance, if you have a camera that supports a maximum exposure of 15 seconds, the Accumulator camera interface would allow you to create a synthetic 30s exposure by combining two 15s exposures.

The INDI Accumulator only supports INDI based cameras.

Key Settings:
1. Accumulator Max Sub-exposure - The maximum exposure of each individual sub-exposure.
1. Even Exposures
    * Enabled - A 14.5 second exposure with a 1 second max sub-exposure will result in 15 sub-exposures at 0.966666s each.
    * Disabled - A 14.5 second exposure with a 1 second max sub-exposure will result in 15 sub-exposures, 14 one second exposures, and a 0.5 second final exposure.

## INDI (Passive)
The INDI Passive interface is a special interface for allowing a second installation of indi-allsky to receive images from a camera (via an indiserver) which is being managed by another instance of indi-allsky.  The Passive interface does not allow changing any settings or taking exposures, it relies on the primary indi-allsky instance to control the camera.  The Passive instance just receives all of the images requested by the primary instance.