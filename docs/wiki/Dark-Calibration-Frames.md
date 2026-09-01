# General
indi-allsky fully automates the capture and processing of master dark calibration frames.  Currently, sigma clipping and average methods are supported.

## RAW mode

Dark frames work best when created from RAW, unprocessed sources.  It not recommended to generate dark frames from JPEG, PNG or other RGB sources, but it is possible.


### Update Dec 2023
It is now possible to generate dark frames from JPEG and PNG devices such as IP web cameras that do not support RAW mode.

**Note: It is only possible to use the `average` mode when generating dark frames with RGB data**

### Altair & Touptek
The Altair and Touptek drivers start color cameras in INDI_RGB mode by default.  You must update the configuration to set the cameras to INDI_RAW mode

https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config#touptek--altair-raw-mode


### Canon DSLR

Canon cameras are normally started in JPEG mode by default and must be set to RAW mode.

https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config#canon-resolution-and-raw-mode


## Acquire Dark Frames
1. Cover your camera lens with something thick enough to block *ALL* light.
1. Stop indi-allsky service
    ```
    systemctl --user stop indi-allsky
    ```
1. Enter the indi-allsky git checkout folder
    ```
    cd indi-allsky
    ```
1. Activate the indi-allsky python virtual environment
    ```
    source virtualenv/indi-allsky/bin/activate
    ```
1. Run darks.py to capture and stack dark frames
    ```
    # Use "sigmaclip" if your camera returns 16-bit RAW data
    ./darks.py sigmaclip

    # Use "average" if your camera returns RGB data
    ./darks.py average
    ```

* Darks will be generated in 5 second increments for the configured gain for night, moonmode, and day frames.
    * 10 exposures at each gain level are used to create the master darks.  The number of frames is configurable with `--Count`.
* This operation can take a while depending on your maximum exposure.
    * 15s maximum exposure requires about 20 minutes to generate master darks
    * 30s maximum exposure requires about 45 minutes
    * 45s maximum exposure requires about 1.5 hours
    * 60s maximum exposure requires about 2.5 hours

## Options

* `sigmaclip` - Capture and stack dark using sigma clipping
* `average` - Capture and stack dark frames using average values
* `tempaverage` - Capture and stack (average) a set of dark frames for every 5c degrees of temperature change
* `tempsigmaclip` - Capture and stack (sigma clipping) a set of dark frames for every 5c degrees of temperature change
* `flush` - Delete all existing dark frames

## Overrides
* `--Count` - The number of exposures to stack for each exposure level (default: 10)
* `--Time_delta` - The time delta between each exposure level (default: 5 seconds)
* `--temp_delta` - The temperature delta between each exposure set (default: 5 degrees)
* `--no-daytime` - Disable generating daytime dark calibration frames
* `--reverse` - Take images in reverse order
* `--bitmax` - Maximum bit depth of camera (default: 16)
* `--gains` - Specify a list of alternative gains instead of those defined in the config

## Temperature calibrated darks

Using the `tempaverage` or `tempsigmaclip` options will generate a series of master darks at every 5c degree decrease.  Every 5c degree drop, a full set of darks will be generated at 5s exposure increments.  Generating daytime dark frames is automatically disabled in these modes.

I would recommend a 3-6 foot USB cable so the camera can be placed in a freezer or refrigerator appliance while the computer can be kept room temperature.  As soon as the camera is placed in the freezer, start the darks.py program with the `tempsigmaclip` option.  A series of master darks will be generated at the initial temperature.  The program will then wait for the camera to decrease 5c degrees from the initial temperature and take a new series.  This will happen until the camera reaches equilibrium with the freezer.  When the minimum temperature is reached, the program will have to be manually cancelled with `control-c`.

If the camera's temperature drops too fast, consider wrapping the camera in a single layer plastic freezer bag to slow down the rate of cooling.  Flush the darks and re-warm the camera to room temperature before restarting the process.

## Removing dark frames

You may delete all of the existing dark frames by running the `flush` command

```
# navigate to indi-allsky git checkout folder
cd indi-allsky
```

```
source virtualenv/indi-allsky/bin/activate

./darks.py flush
```