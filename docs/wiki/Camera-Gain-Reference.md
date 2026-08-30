# Overview
Gain on a camera is defined as the pre-amplification of the light signal/photons before being converted to a digital value.  Altering gain is a way of increasing or decreasing dynamic range.  Increasing gain (for night time) generally _decreases_ dynamic range to provide better visual representation of the data being received by the camera sensor.  

## Gain Terms
* `Decibel` or `dB` - Logarithmic unit of measurement used to express signal amplification
* `ISO` - Exponential unit of measurement in camera sensors to express signal amplification
* `ADU` - Analog-to-Digital unit - The conversion of the sensors/pixels analog reading to a digital value
* `e⁻/ADU` - Indicates the number of photo-electrons required to equal 1 ADU
* `Unity Gain` - The gain setting for a sensor where 1 photo-electron (e⁻/ADU) is converted to 1 ADU
* `Analog Gain` - Native hardware gain amplification
* `Digital Gain` - Software gain amplification


## ISO vs decibels [dB]
* ISO is a more human friendly method of expressing sensitivity to light.  If you want to double the brightness of a scene, you may either `double the exposure` or `double the ISO`.  Halving the brightness can be achieved by halving the ISO.  The following ISO changes will result in a doubling brightness:
  * ISO 100 -> ISO 200
  * ISO 200 -> ISO 400
  * ISO 400 -> ISO 800
  * etc

* decibels are a logarithmic expression of sensitivity to light.  Doubling the brightness of a scene can be achieved by `doubling the exposure` or `increasing the dB by 6.02`.  Halving the brightness can be achieved by reducing the dB by 6.02.  The following dB changes will result in a doubling of brightness:
  * 0 db -> 6.02 dB
  * 5 db -> 11.02 dB
  * 14.5 dB -> 20.52 dB


## Analog Gain Limits
Image sensors can natively amplify the light signal by applying gain.  Analog gain is a hardware function to increase the signal levels while still controlling noise levels.  It is possible to configure the sensor gain beyond the analog gain limits, but after a given gain level, only digital gain is applied.  It is much preferred to stay within the limits of analog gain which provides true hardware signal amplification without amplifying [some] sources of noise.  Digital gain amplifies both signal and noise at the same rate and has no benefit to the final data.


### libcamera
| Sensor   | Max Analog Gain | libcamera Model   | Value |
| -------- | --------------- | ----------------- | ----- |
| IMX447   | 27.0 dB         | RPi HQ Camera     | 22.26 |
| IMX708   | 24.0 dB         | Raspi Camera v3   | 16.0  |
| IMX296   | 24.0 dB         | Raspi Global Shutter | 16.0 |
| IMX462   | 29.4 dB         | IMX462            | 29.51 |

### Astronomy Cameras
| Sensor   | Max Analog Gain | ZWO Model | Value | ToupTek Model | Value |
| -------- | --------------- | --------- | ----- | ------------- | ----- |
| IMX676   | 30.0 dB         | ASI676    | 300   | AE676         | 3162  |
| IMX678   | 30.3 dB         | ASI678    | 303   | G3M678        | 3273  |
| IMX662   | 30.3 dB         | ASI662    | 303   | G3M662        | 3273  |
| AR0130CS |                 | ASI120    |       |               |       |
| IMX224   |                 | ASI224    |       | G3M224        |       |
| IMX290   | 30.0 dB         | ASI290    | 300   | GPCMOS02000KPA | 3162 |
| IMX385   | 30.0 dB         | ASI385    | 300   |               | 3162  |
| IMX178   | 27.0 dB ??      | ASI178    | 270   |               | 2238  |
| IMX462   | 29.4 dB         | ASI462    | 294   | GPM462        | 2951  |
| IMX715   | 30.3 dB         | ASI715    | 303   |               | 3273  |
| IMX485   |                 | ASI485    |       |               |       |
| IMX585   |                 | ASI585    |       |               |       |
| IMX183   | 27.0 dB         | ASI183    | 270   |               | 2238  |
| IMX533   | 36.0 dB         | ASI533    | 360   |               | 6309  |
| IMX294   | 27.0 dB         | ASI294MC  | 270   |               | 2238  |
| IMX492   |                 | ASI294MM  |       |               |       |
| MN34230  |                 | ASI1600   |       |               |       |
| IMX571   | 36.0 dB         | ASI2600   | 360   | ATR2600       | 6309  |

## Vendor Reference
### ZWO Gain
Most modern ZWO cameras configure gain in steps of 1/10th of a dB with a range of 0 to 600.  A gain of 200 equals 20.0dB of gain.

$$
dB = \frac{Gain}{10}
$$

Reverse

$$
Gain = 10 \cdot dB
$$

#### ZWO ASI120
These are legacy cameras which do not necessarily follow the standard above.  Gain is expressed in a value of 0 to 100.  Actual unit correlation is unknown. _NEEDS VERIFICATION_


### PlayerOne Astronomy
Same as ZWO ASI


### libcamera gain
Solid information about gain for libcamera is hard to find.  I believe the modern libcamera versions gain is expressed as 1/100th of ISO.  The normal range of analog gain is 1 to 16 or 22.26.  Gain 1.0 equals ISO 100.

Making the assumption that ISO 100 = 0dB of gain

$$
dB = 20 \cdot log_{10}\left(Gain\right) 
$$

Reverse

$$
Gain = 10^{\left(\frac{dB}{20}\right)}
$$


### ToupTek gain
ToupTek expresses gain with a value of 100 to 10000 which is basically an ISO value.  Gain can be converted to dB using the following formula:

$$
dB = 20 \cdot log_{10}\left(\frac{Gain}{100}\right) 
$$

Reverse

$$
Gain = 100 \cdot 10^{\left(\frac{dB}{20}\right)}
$$


### QHY gain
Some QHY cameras expresses gain directly in dB.  A gain of 3.0 is equal to 3dB of gain.

Other QHY cameras express gain with a range of 0-4000.  Unit correlation is unknown. _NEEDS VERIFICATION_


## Gain calculations
Note:  All gain values calculated with decibels `dB`

### Maintain brightness when adjusting exposure
$$
NewGain = CurrentGain + \left(20 \cdot log_{10}\left(\frac{CurrentExposure}{NewExposure}\right)\right)
$$

### Alter gain instead of exposure
$$
NewGain = CurrentGain + \left(20 \cdot log_{10}\left(\frac{NewExposure}{CurrentExposure}\right)\right)
$$

### Maintain brightess when adjusting gain
$$
NewExposure = CurrentExposure \cdot 10^\left(\frac{CurrentGain - NewGain}{20}\right)
$$

### Alter exposure instead of gain
$$
NewExposure = CurrentExposure \cdot 10^\left(\frac{NewGain - CurrentGain}{20}\right)
$$