# General
indi-allsky provides a new web service API to synchronize images and videos to a remote indi-allsky [web] server.  indi-allsky is now capable of being its own remote web server instance.

### Note

_The indi-allsky web interface requires the use of a Virtual Private Server [VPS] where you have root access to be able to install packages and services.  A web hosting account, which hosts mainly PHP sites, is not sufficient to support indi-allsky._

## Terms
* `local` - The server connected to the camera
* `remote` - The server receiving the uploaded files

## Distributions
* Ubuntu 26.04
* Ubuntu 24.04
* Ubuntu 22.04
* Debian 13 (Raspberry Pi OS 13)
* Debian 12 (Raspberry Pi OS 12)
* Debian 11 (Raspberry Pi OS 11)


## Install Remote Server

### Method 1: APT Package Installation (Recommended)
On your remote VPS or cloud server running Debian or Ubuntu, install the standalone web dashboard package via the official APT repository:

```bash
# 1. Add GPG Keyring
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.indi-allsky.org/key.gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/indi-allsky.gpg
sudo chmod a+r /etc/apt/keyrings/indi-allsky.gpg

# 2. Add APT Repository Source
sudo tee /etc/apt/sources.list.d/indi-allsky.sources <<EOF
Types: deb
URIs: https://apt.indi-allsky.org
Suites: $(lsb_release -cs)
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/indi-allsky.gpg
EOF

# 3. Install Web-Only Package
sudo apt update
sudo apt install -y indi-allsky-web
```

> [!TIP]
> `indi-allsky-web` provides the Flask dashboard, Gunicorn application server, and web server configuration for remote sync portals without requiring camera hardware or local INDI drivers.

---

### Method 2: Manual Source Installation (`web_only_setup.sh`)
```bash
./misc/web_only_setup.sh
```

## Generate API key
On the remote indi-allsky server, after the web server is deployed, generate an API key for the remote user.  You may create a dedicated user account for the sync activity.

* Create user

        source virtualenv/indi-allsky/bin/activate
        
        $ ./misc/usertool.py adduser -u syncuser
        Password (not echoed):
        Password (again):
        Name: SyncAPI user
        Email: foo@example.com

* Set admin

        $ ./misc/usertool.py setadmin -u syncuser

* Generate API key

        $ ./misc/usertool.py genapikey -u syncuser

        API key: 00000000000000000000000000000000000000000000000000

## Setup syncapi
Navigate to the config URL in the local server and enable the SyncAPI and add the following details.

* Remote base URL
* Username
* API key

Save and restart

### Enable multiple upload workers (optional)
You may also enable multiple upload workers so that a single transfer does not halt all upload activities.  More workers requires more memory to support the additional processes.  2GB of memory is recommended for additional workers.


## Timestamps and Timezones
Dates in the indi-allsky database are set to the local time of the local server running capture and are **NOT** UTC and **NOT** timezone aware.  

As of March 2023, for SyncAPI, the timestamps of assets are remapped to the local time of the remote server.  Meaning if a video has a createDate timestamp of 3:05am Pacific Standard Time [PST] and the remote server is set to Eastern Standard Time [EST], the file on the remote server will be 3:05am.

All time calculations for the web interface are offset based on the camera timezone.  If it is currently 6:00am EST, "now" for a camera in located in PST will be 3:00am.


# S3 and SyncAPI integration
## Use Non-Local Images S3
If you are uploading images to S3, you can configure the web interface to serve images from S3 on the **REMOTE** SyncAPI server.  (This is not necessary on the local server since the related settings are used from the Config Admin tab)
```
sqlite3 -table -header /var/lib/indi-allsky/indi-allsky.sqlite

sqlite> SELECT id, name, friendlyName, web_nonlocal_images, web_local_images_admin FROM camera;
+----+------------------+--------------+---------------------+------------------------+
| id |       name       | friendlyName | web_nonlocal_images | web_local_images_admin |
+----+------------------+--------------+---------------------+------------------------+
| 1  | CCD Simulator    |              | 0                   | 0                      |
| 2  | ZWO CCD ASI290MM |              | 0                   | 0                      |
+----+------------------+--------------+---------------------+------------------------+

sqlite> UPDATE camera SET web_nonlocal_images=1 WHERE id=1;
```

### (Optional) Admin local images
If you want to serve local images on admin networks (but serve S3 from non-admin networks) when uploading to S3
```
sqlite> UPDATE camera SET web_nonlocal_images=1 WHERE id=1;
sqlite> UPDATE camera SET web_local_images_admin=1 WHERE id=1;
```


# API Overview

The SyncAPI is roughly idiomatic with a standard REST API, however there are some deviations.

Images and videos have two components that are required for uploads:
1. Metadata (create date, exposure, gain, etc)
1. The file itself

Normally, in a REST service, data is added using a JSON request, however in order to minimize the number of calls required to upload a file, the POST, PUT, and DELETE methods are implemented as a `multipart/form-data` form upload.  The metadata and media file are uploaded as two separate file objects and processed in the same request.

## Endpoints
| Type             | Endpoint                | Note |
| ---------------- | ----------------------- | ---- |
| CAMERA           | sync/v1/camera          |      |
| IMAGE            | sync/v1/image           |      |
| VIDEO            | sync/v1/video           |      |
| MINI_VIDEO       | sync/v1/minivideo       |      |
| KEOGRAM          | sync/v1/keogram         |      |
| STARTRAIL        | sync/v1/startrail       |      |
| STARTRAIL_VIDEO  | sync/v1/startrailvideo  |      |
| PANORAMA_IMAGE   | sync/v1/panoramaimage   |      |
| PANORAMA_VIDEO   | sync/v1/panoramavideo   |      |
| THUMBNAIL        | sync/v1/thumbnail       |      |
| RAW_IMAGE        | sync/v1/rawimage        | not currently used |
| FITS_IMAGE       | sync/v1/fitsimage       | not currently used |

## Methods
* GET - returns file ID and URI
* POST - upload and add file (will not overwrite existing file)
* PUT - upload and add/overwrite file
* DELETE - delete file

