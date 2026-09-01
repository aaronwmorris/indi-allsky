# General

Contents of the misc/ folder in indi-allsky

| Script                   | Description |
| ------------------------ | ----------- |
| adsb_test.py             | Test ADS-B aircraft tracking config |
| aurora_cron.py           | Updates aurora and smoke data for remote installs of indi-allsky |
| build_indi.sh            | Downloads and compiles indi and indi-3rdparty |
| build_libcamera.sh       | Downloads and compiles libcamera and rpicam utils |
| camera_change.sh         | Reconfigures indiserver for new camera without having to run full setup.sh |
| camera_properties.py     | Dumps the camera properties and names |
| convert_db.py            | Migrates data from SQLite to MySQL database |
| create_thumbnails.py     | Generates thumbnails for images created before the thumbnail code was implemented |
| example_ccd_temp.py      | Example script for external CCD temperature data |
| example_ccd_temp.sh      | Example script for external CCD temperature data |
| expire_images.py         | Manual image and video expiration |
| flush_images.py          | Delete all images and (optionally) videos |
| home_assistant_auto_discovery.py | Creates Home Assistant Auto-Discovery topics for indi-allsky |
| import_darks_frames.py   | Imports existing dark frames into database |
| libcamera_enable_dpc.sh  | Re-enables Defective Pixel Correction for libcamera |
| mysql_optimize.sh        | Runs optimize against indi-allsky mysql tables |
| oci_config_test.py       | Oracle Cloud test script |
| populate_data.py         | Populates data for older images that is now automatically generated |
| rebuild_pyindi-client.sh | Re-builds pyindi-client, ignoring cached wheels |
| sensor_test.py           | Test hardware sensor configuration |
| setup_gpsd.sh            | Install and basic setup for gpsd |
| setup_hotspot.sh         | Setup basic WIFI hotspot using NetworkManager |
| setup_mosquitto.sh       | Install and basic etup for mosquitto MQTT broker |
| setup_rtc_i2c.sh         | Setup of I2C real-time clock module |
| setup_usb_automount.sh   | Setup of udisk2 automount for USB devices |
| support_info.sh          | Generate Support Info |
| upload_sync.py           | Script to retry failed uploads |
| usertool.py              | CLI user management tool for indi-allsky |
| validate_db_entries.py   | Validates image and video files referenced in the database |
| web_only_setup.sh        | Simplified setup.sh replacement for web-only installs of indi-allsky |
