# Overview
indi-allsky supports several views to redirect requests to the latest images or videos.  This is achieved by returning a 302 redirect to the asset.  These views allow you to integrate the latest image into another web site.

## Direct file redirects
These redirect directly to the image or video file

### Curl download example
```
curl -L -o "latest_$(date +%Y%m%d_%H%M%S).jpg" https://localhost/indi-allsky/latestimage
```

### Latest Image
Redirects to latest timelapse image file
* https://hostname.local/indi-allsky/latestimage
    * Optional Parameters
        * `camera_id` - Camera ID

### Latest Keogram
Redirects to latest keogram image file
* https://hostname.local/indi-allsky/latestkeogram
    * Optional Parameters
        * `camera_id` - Camera ID
        * `night` - 0 for day, 1 for night

### Latest Startrail
Redirects to latest startrail image file
* https://hostname.local/indi-allsky/lateststartrail
    * Optional Parameters
        * `camera_id` - Camera ID


### Latest Panorama Image
Redirects to latest panorama image file
* https://hostname.local/indi-allsky/latestpanorama
    * Optional Parameters
        * `camera_id` - Camera ID


### Latest RAW Image
Redirects to latest RAW image file
* https://hostname.local/indi-allsky/latestraw
    * Optional Parameters
        * `camera_id` - Camera ID


### Latest Timelapse Video
Redirects to latest timelapse video
* https://hostname.local/indi-allsky/latesttimelapse
    * Optional Parameters
        * `camera_id` - Camera ID
        * `night` - 0 for day, 1 for night

### Latest Startrail Timelapse Video
Redirects to latest startrail timelapse video
* https://hostname.local/indi-allsky/lateststartrailvideo
    * Optional Parameters
        * `camera_id` - Camera ID

### Latest Panorama Video
Redirects to latest panorama video
* https://hostname.local/indi-allsky/latestpanoramavideo
    * Optional Parameters
        * `camera_id` - Camera ID
        * `night` - 0 for day, 1 for night


## View redirects
These redirect to the templated view for the media
### Latest Timelapse Image view
* https://hostname.local/indi-allsky/latestimageview
    * Optional Parameters
        * `camera_id` - Camera ID

### Latest Keogram view
* https://hostname.local/indi-allsky/latestkeogramview
    * Optional Parameters
        * `camera_id` - Camera ID
        * `night` - 0 for day, 1 for night

### Latest Startrail view
* https://hostname.local/indi-allsky/lateststartrailview
    * Optional Parameters
        * `camera_id` - Camera ID

### Latest Panorama Image view
* https://hostname.local/indi-allsky/latestpanoramaview
    * Optional Parameters
        * `camera_id` - Camera ID

### Latest RAW Image view
* https://hostname.local/indi-allsky/latestrawview
    * Optional Parameters
        * `camera_id` - Camera ID


### Latest Timelapse Video view
* https://hostname.local/indi-allsky/latesttimelapsewatch
    * Optional Parameters
        * `camera_id` - Camera ID
        * `night` - 0 for day, 1 for night

### Latest Startrail Video view
* https://hostname.local/indi-allsky/lateststartrailvideowatch
    * Optional Parameters
        * `camera_id` - Camera ID

### Latest Panorama Video view
* https://hostname.local/indi-allsky/latestpanoramavideowatch
    * Optional Parameters
        * `camera_id` - Camera ID
        * `night` - 0 for day, 1 for night

