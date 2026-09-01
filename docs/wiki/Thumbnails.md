# Overview

Thumbnails are now supported for the following object types:

* Timelapse Images
* Keograms
* Startrails Images

Thumbnails are generated in realtime when the asset is created.

## Generating Thumbnails for older images

A script is available to generate thumbnails for pre-existing images.

```
source virtualenv/indi-allsky/bin/activate

./misc/create_thumbnails.py
```

NOTE: If you use the SyncAPI, the script will have to be run on the remote system, as well.