# Overview

Thumbnails are now supported for the following object types:

* Timelapse Images
* Keograms
* Startrails Images

Thumbnails are generated in realtime when the asset is created.

## Generating Thumbnails for older images

### Debian Package Installations (`indi-allsky-ctl`)
```bash
sudo indi-allsky-ctl rebuild-thumbnails
```

### Legacy Source / `setup.sh` Installations
```bash
source virtualenv/indi-allsky/bin/activate
./misc/create_thumbnails.py
```

> [!NOTE]
> If you use the SyncAPI, the command will have to be run on the remote system, as well.