# General

Contents of the `misc/` folder in indi-allsky.

> [!TIP]
> On Debian package installations, many of these maintenance, setup, and diagnostic scripts are exposed directly via the unified [`indi-allsky-ctl`](indi-allsky-ctl) command-line utility without needing to manually activate virtual environments.

| Script | Description | `indi-allsky-ctl` Command |
| ------ | ----------- | ------------------------- |
| `add_notification.py` | Add alert notification to database | `indi-allsky-ctl notify` |
| `adsb_test.py` | Test ADS-B aircraft tracking config | `indi-allsky-ctl test-adsb` |
| `aurora_cron.py` | Updates aurora and smoke data for remote installs | *(daemon/cron service)* |
| `backup_database.py` | Create SQLite database backup | `indi-allsky-ctl backup-db` |
| `build_indi.sh` | Downloads and compiles indi and indi-3rdparty | *(developer script)* |
| `build_libcamera.sh` | Downloads and compiles libcamera and rpicam utils | *(developer script)* |
| `camera_change.sh` | Reconfigures indiserver for new camera | *(legacy)* |
| `camera_info.py` | Detailed camera sensor specifications | `indi-allsky-ctl camera-info` |
| `camera_linearity.py` | Camera exposure linearity test | `indi-allsky-ctl test-linearity` |
| `camera_properties.py` | Dumps the camera properties and names | `indi-allsky-ctl camera-props` |
| `camera_test.py` | Captures test image from camera | `indi-allsky-ctl test-camera` |
| `convert_db.py` | Migrates data from SQLite to MySQL database | `indi-allsky-ctl convert-db` |
| `create_thumbnails.py` | Generates missing thumbnails | `indi-allsky-ctl rebuild-thumbnails` |
| `device_test.py` | Test fans, dew heaters, and GPIO outputs | `indi-allsky-ctl test-devices` |
| `example_ccd_temp.py` | Example script for external CCD temperature data | *(example hook)* |
| `example_ccd_temp.sh` | Example script for external CCD temperature data | *(example hook)* |
| `expire_images.py` | Manual image and video expiration | `indi-allsky-ctl expire-images` |
| `flush_16min_images.py` | Purge recent 16 min images from DB | `indi-allsky-ctl flush-16min-images` |
| `flush_images.py` | Delete all images and (optionally) videos | `indi-allsky-ctl flush-images` |
| `home_assistant_auto_discovery.py` | Creates Home Assistant Auto-Discovery topics | `indi-allsky-ctl ha-discovery` |
| `import_darks_frames.py` | Imports existing dark frames into database | `indi-allsky-ctl import-darks` |
| `indi_list_cameras.py` | List connected INDI cameras | `indi-allsky-ctl list-cameras` |
| `merge_cameras.py` | Merge camera DB records | `indi-allsky-ctl merge-cameras` |
| `mysql_optimize.sh` | Runs optimize against indi-allsky mysql tables | `indi-allsky-ctl optimize-mysql` |
| `oci_config_test.py` | Oracle Cloud Infrastructure config test script | `indi-allsky-ctl test-oci` |
| `populate_data.py` | Populates data for older images | *(internal utility)* |
| `rebuild_pyindi-client.sh` | Re-builds pyindi-client, ignoring cached wheels | *(developer script)* |
| `sensor_test.py` | Test hardware sensor configuration | `indi-allsky-ctl test-sensors` |
| `setup_disable_leds.sh` | Disable onboard LEDs on Raspberry Pi | `indi-allsky-ctl disable-leds` |
| `setup_gpsd.sh` | Install and basic setup for gpsd | `indi-allsky-ctl setup-gps` |
| `setup_hotspot.sh` | Setup basic WIFI hotspot using NetworkManager | `indi-allsky-ctl setup-hotspot` |
| `setup_mosquitto_mqtt.sh` | Install and setup Mosquitto MQTT broker | `indi-allsky-ctl setup-mqtt` |
| `setup_rtc_i2c.sh` | Setup of I2C real-time clock module | `indi-allsky-ctl setup-rtc` |
| `setup_usb_automount.sh` | Setup of udisks2 automount for USB devices | `indi-allsky-ctl setup-usb-mount` |
| `support_info.sh` | Generate Support Info bundle | `indi-allsky-ctl support-info` |
| `test_websocket_events.py` | WebSocket event listener & remote actions | `indi-allsky-ctl test-websocket` |
| `upload_sync.py` | Retry and synchronize pending uploads | `indi-allsky-ctl retry-uploads` |
| `upload_test.py` | Test transfer endpoints (SFTP/S3/Sync API) | `indi-allsky-ctl test-upload` |
| `usertool.py` | CLI user management tool for indi-allsky | `indi-allsky-ctl user-add/passwd/...` |
| `validate_db_entries.py` | Validates image and video files in database | `indi-allsky-ctl validate-db` |
| `web_only_setup.sh` | Simplified setup.sh for web-only installs | *(installer)* |
