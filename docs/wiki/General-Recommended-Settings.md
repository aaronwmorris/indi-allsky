# Overview
These settings are general recommendations for camera settings.

1. Set camera to 16-bit RAW mode (if supported)
    * INDI settings can be found here:  https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config
1. Use SCNR [Image tab] to remove the green bias
1. Stretching [Image tab]
    * Standard Deviation Cutoff with cutoff of `2.25`
    * or Midtone Transer Function [MTF] - Shadow cutoff `0.03`
1. Take Dark Frames to remove Hot Pixels
1. Use Image Circle Mask [Processing tab] to remove edges of camera barrel
1. Use the Image Processor to test different image processing settings
    * Requires FITS (RAW) files to test


## Single Board Computer (ie Rasberry Pi)
* Use a CPU heatsink
* Use a CPU Fan to cool your system
* Disable LEDs (available in setup) to eliminate reflections in your enclosure
* Enable Hardware Watchdog (available in setup) to automatically reboot your system if it locks up
* Use a dew heater to eliminate dew on your dome
    * 1-2 watts is generally sufficient in most climates
    * The heat emitted by the CPU might be sufficient to remove dew assuming there is unobstructed airflow between the main chamber of your enclosure and the dome.
* Use an Ethernet connection instead of Wi-Fi
    * PoE is a great way to combine power and connectivity
* If using Wi-Fi, disable Power Saving (available in Tools -> Network)
* Raspberry Pi 5 - An official 5V-5A 27W power supply is strongly recommended.  Failure to do this can result in system instability.
    * or PoE+ 802.3at [30W] (PoE 802.3af 15W is not sufficient for Pi5)


## Raspberry Pi HQ Camera
https://github.com/aaronwmorris/indi-allsky/wiki/Raspberry-PI-HQ-Camera