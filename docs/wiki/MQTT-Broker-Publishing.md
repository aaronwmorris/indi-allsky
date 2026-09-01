# General
indi-allsky has the built-in capability to publish data from your all sky camera to an MQTT broker service.

You can find the settings related to the MQTT service in the configuration form.

## Home Assistant Auto-Discovery
Included is a script to publish the auto-discovery topics for Home Assistant.  The script only requires a few seconds to run and only needs to be run once.  Images and other sensors related to your allsky camera will automatically populate on your dashboard.

First, setup the MQTT integration in Home Assistant.  After the integration is enabled, run the script below.  **If you run the script before the integration is setup, no entities will be displayed.** Just re-run the script again.

```
source virtualenv/indi-allsky/bin/activate

./misc/home_assistant_auto_discovery.py
```

## Topics
The default base topic is `indi-allsky/`.  This can be overridden in the config section.
| Topic                  | Type      | Data |
| ---------------------- | --------- | ---- |
| indi-allsky/latest     | bytearray | Latest binary image |
| indi-allsky/sqm        | float     | SQM value |
| indi-allsky/stars      | int       | Number of stars detected |
| indi-allsky/exp_date   | str       | Exposure date and time |
| indi-allsky/exposure   | float     | Last camera exposure |
| indi-allsky/bin        | int       | Camera bin value |
| indi-allsky/temp       | float     | Last camera temperature reading |
| indi-allsky/sunalt     | float     | Sun altitude |
| indi-allsky/moonalt    | float     | Moon altiude |
| indi-allsky/moonphase  | float     | Moon phase % |
| indi-allsky/mooncycle  | float     | Moon cycle % |
| indi-allsky/moonmode   | bool      | True if indi-allsky has detected moon mode |
| indi-allsky/night      | bool      | True if indi-allsky is in night mode |
| indi-allsky/latitude   | float     | Latitude |
| indi-allsky/longitude  | float     | Longitude |
| indi-allsky/sidereal_time | str    | Sidereal time |
| indi-allsky/kpindex       | float  | Global Kp-index |
| indi-allsky/ovation_max   | int    | Max Aurora Ovation score for location |
| indi-allsky/smoke_rating  | str    | Smoke Rating |
| indi-allsky/aircraft      | int    | Count of visible Aircraft (ADS-B) |
| indi-allsky/cpu/user      | float  | User CPU Usage (percent) |
| indi-allsky/cpu/system    | float  | System CPU Usage |
| indi-allsky/cpu/nice      | float  | Nice CPU Usage |
| indi-allsky/cpu/iowait    | float  | IO Wait CPU Usage |
| indi-allsky/cpu/total     | float  | Total CPU Usage |
| indi-allsky/memory/user   | float  | Memory Usage (percent) |
| indi-allsky/memory/cached | float  | Cached Memory Usage |
| indi-allsky/memory/total  | float  | Total Memory Usage |
| indi-allsky/disk/root     | float  | Root Filesystem Usage (percent) |
| indi-allsky/disk/MOUNTPOINT | float  | Filesystem Usage (for each mountpoint) |
| indi-allsky/temp/SYS/LABEL  | float  | Temperature<br/>Example for RPi 3: `indi-allsky/temp/cpu_thermal/0`<br />The System page will show the same names used in MQTT |

| Topic                  | Type      | Data |
| ---------------------- | --------- | ---- |
| indi-allsky/sensor_temp_0 | float  | Camera temperature |
| indi-allsky/sensor_temp_1<br>indi-allsky/sensor_temp_2<br>...<br>indi-allsky/sensor_temp_9 | float  | Reserved |
| indi-allsky/sensor_temp_10<br>indi-allsky/sensor_temp_11<br>...<br>indi-allsky/sensor_temp_29 | float  | System Temperature Data |

| Topic                  | Type      | Data |
| ---------------------- | --------- | ---- |
| indi-allsky/sensor_user_0 | float  | Camera temperature |
| indi-allsky/sensor_user_1 | float  | Dew Heater Duty Cycle |
| indi-allsky/sensor_user_2 | float  | Dew Point |
| indi-allsky/sensor_user_3 | float  | Frost Point |
| indi-allsky/sensor_user_4 | float  | Fan Duty Cycle |
| indi-allsky/sensor_user_5 | float  | Heat Index |
| indi-allsky/sensor_user_6 | float  | Wind direction (degrees) |
| indi-allsky/sensor_user_7 | float  | SQM Magnitude |
| indi-allsky/sensor_user_8<br>indi-allsky/sensor_user_9<br> | float  | Reserved |
| indi-allsky/sensor_user_10<br>indi-allsky/sensor_user_11<br>...<br>indi-allsky/sensor_user_29 | float  | User sensor data |

## Local broker
Included in the repository is a script that an quickly deploy a Mosquitto MQTT broker to your system.

The script is at `./misc/setup_mosquitto.sh`.  The script will ask for a password for the `indi-allsky` mqtt user.

Mosquitto will be setup with the following ports:
| Port | Service |
| ---- | ------- |
| 1883 | mqtt no encryption (loopback only) |
| 8883 | mqtt with encryption |
| 8080 | websockets no encryption (loopback only) |
| 8081 | websockets with encryption |

## MQTT clients
You can use a mqtt client such as `MQTT Dash` on Android to subscribe to a local mosquitto server and view the data published in real-time.
https://play.google.com/store/apps/details?id=net.routix.mqttdash

[[https://github.com/aaronwmorris/indi-allsky/blob/master/content/screenshot_mqtt_dash.jpg | width=300px]]

### CLI
You may subscribe to topics from the CLI to debug the information being passed.

```
mosquitto_sub -d -V mqttv5 -h localhost -p 1883 -u mqtt_username -P password123 -t 'indi-allsky/exposure'
```

Certificate validation will likely fail for `mosquitto_sub`, therefore it is easier to subscribe to the non-TLS port.