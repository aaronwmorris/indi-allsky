# Overview
indi-allsky has full support for operating in a docker containerized environment.  Each component (ie process) is broken out to a separate container, per docker best practices.  (The container list is below)

If you do not already have a docker host setup, it will be necessary to install and setup docker.


### Platforms
* x86_64
    * Linux
    * Windows
    * Mac
* arm64
    * Linux
    * Mac - Apple Silicon (Mac M1+)


## Docker setup
Install docker from the docker repositories.

:triangular_flag_on_post: The version of docker that is distributed with Debian and Ubuntu are too old to properly build the containers, therefore it will be necessary to install the latest version of docker from the main docker repositories.

https://docs.docker.com/engine/install/


### Non-privileged user
You can setup a non-privileged user on your docker host to manage your environment.

```
sudo usermod -a -G docker username

# Logout and login again for change take effect
```


## indi-allsky setup
### Code checkout
The indi-allsky code will need to be checked out on your docker host in order to build the container images.

1. Install git

        sudo apt-get install git

1. Clone the indi-allsky git repository

        git clone https://github.com/aaronwmorris/indi-allsky.git


### Setup
Use the `setup_env.sh` script to setup your `.env` environment file and ssl certificates

1. Navigate to the indi-allky sub-directory

        cd indi-allsky/docker/

        ./setup_env.sh


### Update camera driver
If you have a ZWO/ToupTek/PlayerOne/etc camera, edit the `.env` file to change the driver to the following
```
INDIALLSKY_INDI_CCD_DRIVER=indi_asi_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_toupcam_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_altaircam_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_ogmacam_ccd_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_omegonprocam_ccd
#INDIALLSKY_INDI_CCD_DRIVER=indi_playerone_ccd
```

#### QHY
QHY cameras will not work inside docker due to the way the camera is initialized.  QHY cameras are initially presented as a USB `Cypress WestBridge` device--this is the firmware loader device.  When the firmware is loaded, the Cypress WestBridge device disappears and a new USB camera device becomes available.  Docker privileged containers only pass-through devices that exist _at the time the container is started_.

Starting the `indiserver` container twice may allow QHY to function in a containerized environment.  Once to load the firmware, a second time to map the new device to the indiserver container.


### (Optional) libcamera docker setup
* The CSI/MIPI camera must be setup and available in the docker host before starting the containers
* Uncomment the libcamera build script in `Dockerfile.indi_base_debian13`
* Uncomment `privileged` flag for capture container in `docker-compose.yaml`
* Uncomment udev volume mapping for capture container in `docker-compose.yaml`


## Build containers
```
docker compose build
```

If you experience dependency problems with the build, it may be necessary to manually build the base image first.
```
docker compose build indi.base
```

:warning: Do **NOT** use the `docker-compose` syntax (with the dash) which implies docker compose v1.  Docker compose v2 uses `docker compose`.


## Camera drivers
### INDI
In most cases, INDI (core and 3rd-party) will probably have to be installed on the host running the indiserver container.  The indiserver does **not** need to run on the host, but the host needs to create the device nodes and load the firmware so the indiserver container may connect to the devices.  With privileged containers, only the devices that exist when the container is started are created within the container.

### libcamera
The capture container needs to be `privileged` to permit access to the camera device for libcamera.  A `udev` related folder needs to be mapped to the container, too.  These settings are available, but commented out, in the docker-compose.yaml.

The CSI/MIPI camera must be setup and available in the docker host before starting the containers.  With privileged containers, only the devices that exist when the container is started are created within the container.


## Run containers
```
docker compose up

or

docker compose up --detach
```
Notes
* There are delays up to 120s for services to completely start
* Your camera must be plugged in prior to starting the indiserver_indi_allsky container


## Stop containers
```
docker compose down
```


## Info

The docker compose setup sets up a single container per process.


### Containers

* indiserver.indi.allsky
    * privileged container
* capture.indi.allsky
    * capture process
* gunicorn.indi.allsky
    * python application server
    * Flask database migrations managed here
* webserver.indi.allsky
    * reverse proxy
* mariadb.indi.allsky
    * MariaDB database
* mosquitto.indi.allsky
    * Mosquitto MQTT broker
* indi.base
    * intermediate image
    * does not run
* indi.allsky.base
    * intermediate image
    * does not run


### Exposed Ports

* webserver
    * 8080:80
    * 8443:443
* indiserver
    * 17624:7624
* gunicorn
    * 8000:8000 (commented out)
* mariadb
    * 13306:3306 (commented out)
* mosqutto
    * 18883:8883
    * 18081:8081


### Volumes

* images_indi_allsky
* migrations_indi_allsky (flask)
* database_indi_allsky (MariaDB)
* mosquitto_indi_allsky (Mosquitto)


## Updating indi-allsky
1. Navigate to the current git clone

        cd indi-allsky

1. Pull the latest changes via git

        git pull origin main

1. Rebuild containers
   * capture.indi.allsky
   * gunicorn.indi.allsky
   * webserver.indi.allsky

         docker compose build capture.indi.allsky gunicorn.indi.allsky webserver.indi.allsky


## Special scenarios


### Start only web interface

    docker compose up mariadb.indi.allsky gunicorn.indi.allsky webserver.indi.allsky

## Docker maintenance
Periodically, you may want to clean up artifacts left over by the docker build process.  These commands should not result in any data loss.

* Prune images
    * `docker image prune`
* Prune volumes
    * `docker volume prune`
* Prune full system
    * `docker system prune`
    * :warning: This will delete the intermediate build layers which may trigger a full rebuild if you need to update an image (for a code deploy).

## Run commands in container
You can run some of the command line scripts in the container using the following pattern.  Find the capture container ID by running `docker ps | grep capture.indi.allsky`

### User management
```bash
docker exec -it 012345678901 /home/allsky/venv/bin/python3 /home/allsky/indi-allsky/misc/usertool.py adduser

docker exec -it 012345678901 /home/allsky/venv/bin/python3 /home/allsky/indi-allsky/misc/usertool.py setadmin
```

#### Generate API key
```bash
docker exec -it 012345678901 /home/allsky/venv/bin/python3 /home/allsky/indi-allsky/misc/usertool.py genapikey
```


### Home Assistant Auto-Discovery
```bash
docker exec -it 012345678901 /home/allsky/venv/bin/python3 /home/allsky/indi-allsky/misc/home_assistant_auto_discovery.py
```

### Setup D-Bus connection to read time
```bash
# Create matching user account for allsky
sudo useradd -u 10001 -s /bin/false -M -l allsky-container

# Create dbus policy file
sudo tee /etc/dbus-1/system.d/allsky-timedate-policy.conf << 'EOF'
<!DOCTYPE busconfig PUBLIC
 "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="allsky-container">
    <allow send_destination="org.freedesktop.timedate1"/>
    <allow receive_sender="org.freedesktop.timedate1"/>
    <allow send_destination="org.freedesktop.timedate1"
           send_interface="org.freedesktop.DBus.Properties"/>
    <allow send_destination="org.freedesktop.timedate1"
           send_interface="org.freedesktop.timedate1"/>
  </policy>
</busconfig>
EOF

# Reload dbus configuration
sudo systemctl reload dbus
```

#### Docker compose change

Add to [docker-compose.yaml]
```yaml
services:
  gunicorn.indi.allsky:
    volumes:
      - /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket:ro
```

## Frequently Asked Questions
<details>
  <summary>Why compile INDI from source and not use the PPA?</summary>

***
The Ubuntu [INDI PPA](https://launchpad.net/~mutlaqja/+archive/ubuntu/ppa) is a convenient place to install INDI, however, there have been many instances of package dependency errors or broken functionality.  There is no way to install older packages from the PPA, therefore the only way to have enough control to ensure the system works is to compile from source.

Compiling from source also gives you the opportunity to install older versions or install from HEAD if something needs to be tested.  The git tag for the source code may be changed in your `.env`
***
</details>

<details>
  <summary>Why use Debian instead of Ubuntu?</summary>

***
This is somewhat a personal choice, but I feel Debian is a better choice for the foundation of Open Source Projects.  If Debian has problems for any reason in the future, I will gladly switch to a different base image for the containers.

* https://www.debian.org/intro/about
* https://www.debian.org/social_contract
***
</details>