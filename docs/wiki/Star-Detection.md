# Overview

indi-allsky has two methods for detecting stars.  The method is set under `Config -> Processing` in the Star & Meteor Detection Engine card.

**Template Match** looks for shapes in the image that resemble a small round star.  This is the default.

**SEP** measures the sky background across the frame, subtracts it, and then finds the sources that are left standing above the noise.

## Choosing a method

Template Match looks for one fixed star shape.  Allsky lenses stretch stars near the edges of the frame, so a lot of real stars do not match it.  There is also no measurement of the sky background, so moonlight and cloud change the results.

The bigger issue is that the threshold does not mean anything consistent.  A value that works on a clear night can behave very differently on the next one, so star counts are hard to compare over time.

SEP measures every image against its own background.  A sigma value means the same thing whatever the conditions are.

**Note: Star counts will change if you switch methods.  Treat the threshold as a fresh setting rather than carrying the old one over.**

## Settings

**Star Detection Method** picks the method.  Only the threshold for the method you selected stays editable, the other one is greyed out.

**SEP Sigma Threshold** is how far above the background noise something has to be before it counts as a star.  The default is 5.0.

* 3 - faint stars, and more noise
* 5 - works for most conditions
* 10 - brighter stars only
* 15 and up - only the brightest

**SEP Max Star Radius** ignores anything bigger than the size you set.  The number is about half the width of the object in pixels, so 5 ignores anything wider than roughly 10 pixels.  The default is 20.

Moonlit cloud, bloomed stars and satellite trails get picked up as one large source and counted as a star.  If your count jumps when cloud comes over, lower this.

## Tuning

You do not have to guess at the values.  `Config -> Image Processing` has a Detection Tuning card in the Image tab.

Turn on **Run Detection** and press Process.  The stars and meteors it found are drawn on the preview image and the counts are shown next to it.  Nothing you change here is saved, so you can try values and reprocess as much as you want.  You can switch methods here too and run both against the same image.

Set your detection mask before you touch the thresholds.  Without one, trees and rooftops around the horizon can be more than half of everything detected.  See [Detection Masks](Detection-Masks).

Once you are happy with the values, set them under `Config -> Processing`.
