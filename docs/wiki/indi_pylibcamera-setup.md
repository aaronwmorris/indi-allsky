## OS Distribution

* Recommend `Raspberry Pi OS 12 64-bit (bookworm)` minimum

## Git repo
https://github.com/scriptorron/indi_pylibcamera

#### Bullseye note
It may be possible to install on Raspberry Pi OS 11 (bullseye), but libcamera is an older version.

## Memory
indi_pylibcamera is writtin in Python, therefore, it has higher memory requirements versus other camera drivers.  It is recommended to have at least 2GB of RAM.

## Install system packages

```
sudo apt-get install \
    python3-picamera2 \
    python3-libcamera

# may be necessary
sudo apt-get install \
    libgles2-mesa

```

Note:  It is possible to install `picamera2` in the indi-allsky virtualenv, but it is not possible to install the `libcamera` python modules [in the virtualenv].


## Virtualenv change
System modules must be allowed in the virtualenv

Edit `virtualenv/indi-allsky/pyvenv.cfg` and set `include-system-site-packages = true`

Example:
```
home = /usr/bin
include-system-site-packages = true
version = 3.11.2
executable = /usr/bin/python3.11
command = /usr/bin/python3 -m venv /home/pi/indi-allsky/virtualenv/indi-allsky
```

## Reactivate the virtualenv
```
deactivate
```

## Install indi_pylibcamera
```
source virtualenv/indi-allsky/bin/activate

pip3 install indi-pylibcamera
```

## Upgrade simplejpeg
* The OS distribution of picamera2 installs the distribution version of python3-simplejpeg.  simplejpeg needs to be rebuilt to support the newer version of numpy.
```
pip3 install --upgrade simplejpeg
```

## systemd indiserver unit changes
The indiserver systemd unit must be updated to allow the indi_pylibcamera module to function correctly.  Uncomment the two `Environment` settings and add `indi_pylibcamera`

Note:  **Some of the paths are user, architecture, and python version dependent**

File: `$HOME/.config/systemd/user/indiserver.service`
```
[Unit]
Description=Indi Server
After=network.target

[Service]
#User=pi
Environment="PATH=/home/pi/indi-allsky/virtualenv/indi-allsky/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONPATH=/home/pi/indi-allsky/virtualenv/indi-allsky/lib/python3.11/site-packages:/usr/local/lib/aarch64-linux-gnu/python3.11/site-packages"
ExecStart=%INDI_DRIVER_PATH%/indiserver -p 7624 indi_simulator_telescope indi_pylibcamera
ExecStop=/bin/kill -TERM $MAINPID
RestartSec=5
PrivateTmp=true
UMask=0022

[Install]
WantedBy=default.target
```

## Reload the systemd config
```
systemctl --user daemon-reload
```

## Restart the indiserver
```
systemctl --user restart indiserver
```

## Validation
```
systemctl --user status indiserver
```

This should show something like the following.  If there are any exceptions, something is wrong.
```
● indiserver.service - Indi Server
     Loaded: loaded (/home/pi/.config/systemd/user/indiserver.service; enabled; preset: enabled)
     Active: active (running) since Tue 2024-01-30 11:07:54 CST; 31min ago
   Main PID: 856 (indiserver)
      Tasks: 11 (limit: 817)
        CPU: 6.919s
     CGroup: /user.slice/user-1000.slice/user@1000.service/app.slice/indiserver.service
             ├─856 /usr/local/bin/indiserver -p 7624 indi_simulator_telescope indi_pylibcamera
             ├─890 indi_simulator_telescope
             └─891 /home/pi/indi-allsky/virtualenv/indi-allsky/bin/python3 /home/pi/indi-allsky/virtualenv/indi-allsky/bin/indi_pylibcamera

Jan 30 11:07:54 allsky systemd[708]: Started indiserver.service - Indi Server.
Jan 30 11:07:55 allsky indiserver[856]: 2024-01-30T17:07:55: startup: /usr/local/bin/indiserver -p 7624 indi_simulator_telescope indi_pylibcamera
Jan 30 11:07:55 allsky indiserver[856]: 2024-01-30T17:07:55: Driver indi_simulator_telescope: HaAxis: TrackRate 1, trackingRateDegSec 15.041067 arcsec
```

## INDI config
These are not recommendations, just examples.

### Enable AWB
```json
{
    "SWITCHES": {
        "CAMCTRL_AWBENABLE": {
            "on": [
                "INDI_ENABLED"
            ],
            "off": []
        }
    },
    "PROPERTIES": {},
    "TEXT": {}
}
```