<details>
  <summary>Is indi-allsky a fork of Thomas Jacquin's Allsky?</summary>

***
indi-allsky is **not** a fork of TJ's Allsky.  TJ's Allsky was the inspiration for some of the early settings and semantics, but indi-allsky is a completely unique all sky implementation.  I originally started indi-allsky in late 2020 to operate the new Svbony sv305 color CMOS camera.  It is very difficult to add new cameras to TJ's Allsky and the INDI project had just released Svbony support.

The difficulty of adding camera vendor support to TJ's Allsky is a separate image capture program would have to be written for every camera vendor since TJ's Allsky directly manages the camera.  I bypassed this entirely by using INDI for the camera interface.  indi-allsky is completely hardware agnostic and does not communicate directly with the hardware.  The indiserver manages the hardware and indi-allsky is a standard INDI client which communicates with the indiserver.
***
</details>

<details>
  <summary>What programming language is used in indi-allsky?</summary>

***
indi-allsky is written in Python 3.  indi-allsky was started largely as an experiment to see if Python could even support running an all sky system.  Python has a reputation for being slow, which is a valid criticism.  In the case of indi-allsky, Python is really just the glue language.  Most of the heavy computations are performed by Python modules with C/C++ bindings which greatly enhance the performance of the system.

Some of the modules with C bindings:
* pyindi-client - INDI integration
* OpenCV - Image processing
* Numpy - Image/data processing
* PIL - Image processing
* PycURL - File transfers
***
</details>

<details>
  <summary>Does indi-allsky support my camera?</summary>

***
indi-allsky supports more camera models than any other all sky software.  The answer is almost always "yes" but there are always caveats.

Most astronomy/planetary cameras are well supported.  (In no specific order)
* ZWO (ASI)
* QHY
* Starlight Xpress
* Player One
* Touptek
* Altair
* Svbony

Canon DSLRs are also supported.

Most of the MIPI/CSI camera modules are supported with libcamera on Raspberry Pi 3/4/5 SBCs only.
* imx477 (RaspPi HQ Camera)
* imx378
* imx708 (Camera Module v3)
* Hawkeye (64mp)
* imx219 (Camera Module v1)
* imx296 (Global shutter)

***
</details>

<details>
  <summary>I have a camera that is supported by INDI but is not on your list.</summary>

***
Please open an issue and I will add the support.  If you can connect the camera and connect it to the indiserver with EKOS, then provide the output of `indi_getprop` on the CLI, it would be helpful.

It usually only takes me about 15 minutes to add support for a new camera.  I primarily just need to know how to configure Gain for the camera which is specific to vendors.
***
</details>

<details>
  <summary>Help!  My camera is not detected?</summary>

***
Make sure you selected the correct INDI/libcamera camera server during the setup process.  You can always re-run setup.sh to verify or change camera servers.

If you have changed cameras or changed the camera selection, you may need to restart the indiserver process.

```
systemctl --user restart indiserver
```
***
</details>

<details>
  <summary>What cameras are not supported?</summary>

***
Even though these cameras are on the DO NOT USE list, it may still be possible to use them with the `indi_webcam_ccd` server.  However, the cameras will likely be limited to 1 second exposure times and there is little control over image quality.

* Avoid any MIPI/CSI camera module connected with a USB adapter.
* Avoid USB web cameras

***
</details>

<details>
  <summary>Can I use a Network IP Web Camera with indi-allsky?</summary>

***
**Oct 2023 Update:**  The new pyCurl Camera should allow slightly better IP Web Camera integrations.  The pyCurl Camera supports a standard URL and HTTP authentication options.

The `indi_webcam_ccd` driver supports downloading JPEG images from a remote web server, eg a Network IP camera.  indi-allsky cannot control the exposure or settings on the remote camera, the camera manages itself.

You may need to discover how to download JPEG data directly from your camera module.  Below is a Reolink example.

https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config#webcam---ip-camera---reolink
***
</details>
<details>
  <summary>Can I setup indi-allsky with Astroberry?</summary>

***
Astroberry 3.0 is supported.

Astroberry Server 2.0 is no longer supported.
***
</details>

<details>
  <summary>Why did indi-allsky fail to generate a timelapse video?</summary>

***
If you have a high resolution camera such as a Raspi HQ camera or ASI178, the ffmpeg process which compiles the video might run out of memory.  Check the system logs at `/var/log/syslog` or `/var/log/kern.log` for messages regarding out of memory conditions.

The fix is to set the video scaling to 75% or 50% to reduce the memory requirements.
***
</details>

<details>
  <summary>Why do I need to compile INDI for libcamera support?</summary>

***
There is no hard requirement specifically for the libcamera supported cameras to function, however, indi-allsky makes use of the INDI virtual telescope driver to emulate the function of a camera on a mount.  The data from the virtual telescope is used to determine where the camera is pointing in the sky (zenith is assumed for now).

You may also utilize the GPSd integration with INDI if you have a GPS adapter.

If you know you will not be using an astronomy camera, you can skip building the INDI 3rd party drivers.
***
</details>

<details>
  <summary>I made a setting change.  Why did not take effect?</summary>

***
By default, when you click Save on the config form, the settings are only saved to the config file, but not applied to the running program.  When you want a setting change to take effect, you must enable the `Reload on Save` switch before hitting Save.

Once you do this, it may take 1-2 minutes before you see the results of the settings.  All of the indi-allsky processes have to be restarted for the new settings to take effect.
***
</details>

<details>
  <summary>How do I remove a camera from the dropdown?</summary>

***
The camera entry cannot be removed from the database due to the Foreign Key references in the database.  However, you may hide the camera by setting flag in the database.

https://github.com/aaronwmorris/indi-allsky/wiki/SQL-queries

If you activate a camera in the future after hiding it, the camera will automatically be un-hidden.
***
</details>

<details>
  <summary>Why does my image have a green tint?</summary>

***
By default indi-allsky operates on RAW data from cameras.  By nature, RAW data does not (and cannot) have white balancing included with the data.

Almost all color cameras have a 4 pixel color bayer pattern which includes one red, one blue, and two green pixels in each grouping.  The two green pixels causes images to have a heavy green bias.  indi-allsky includes some SCNR algorithms that were documented by the PixInsight team.
***
</details>

<details>
  <summary>Why is my image solid gray?</summary>

***
This can happen with certain camera models at very low exposures.  indi-allsky starts taking exposures at the lowest possible exposure settings by default.  The data received by indi-allsky is normally RAW data and may be in 8, 10, 12, 14, or 16 bit format--the bit depth must be detected in real time.  Newer cameras with better noise control and hot pixel suppression can confuse the scaling algorithm into thinking higher bit depths are lower and over-scales the image.  This will result in a gray image.

The fix is setting the correct bit depth for the camera (10, 12, 14, or 16).  Alternatively, set the `Default exposure` for your camera to 0.01 or 0.001.
***
</details>

<details>
  <summary>Why does it take indi-allsky 2+ minutes to complete a 60 second exposure?</summary>

***
This is a problem with libcamera and not indi-allsky.  If you attempt to utilize **Auto White Balance [AWB]** with the Raspberry Pi camera modules **at night**, libcamera may end up taking several exposures internally to compute the correct color balance for each image.  There is just not enough illumination at night for the libcamera algorithm to perform color balancing in a single exposure.

This problem only occurs at night, during the day, there is enough light for libcamera to perform its calculations in a single shot.
***
</details>

<details>
  <summary>Does indi-allsky support non-Raspberry Pi hardware?</summary>

***
Yes.  indi-allsky has been tested on many different ARM Single Board Computers [SBC].  Orange Pi, Banana Pi, Rock Pi, etc all work very well.

It is strongly encouraged to use an SBC with 64-bit ARM support and 2+ GB of RAM for the best experience.

Unfortunately, **the Raspberry PI camera modules will only work with Raspberry Pi hardware**.  Dedicated astronomy planetary/deep-sky cameras all work great with alternate hardware.
***
</details>

<details>
  <summary>TJs Allsky's images from the HQ camera look better than indi-allsky</summary>

***
indi-allsky consumes RAW/DNG data by default.  RAW data is generally unprocessed, it is literally the raw data from the image sensor.  Most image software performs optimization/processing on the images before presenting it to the user and this is also true of libcamera.  Processing usually includes debayering, white balance, color corrections, etc.  When you deal with RAW data, all of this must be done manually.

TJ's Allsky ingests JPEG data from libcamera and libcamera performs more processing by default on the JPEG output.  You should be able to get the same output from indi-allsky if you switch the libcamera configuration to provide JPEG data instead of DNG data.
***
</details>