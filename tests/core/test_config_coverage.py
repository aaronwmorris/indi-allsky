import io
import json
import os
import sys
import tempfile
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm.exc import NoResultFound

from indi_allsky.config import IndiAllSkyConfig, IndiAllSkyConfigUtil
from indi_allsky.exceptions import ConfigSaveException
from indi_allsky.flask.models import IndiAllSkyDbConfigTable, IndiAllSkyDbUserTable
from indi_allsky.version import __config_level__


def ensure_system_user(db):
    system_user = IndiAllSkyDbUserTable.query.filter_by(username="system").first()
    if not system_user:
        system_user = IndiAllSkyDbUserTable(
            username="system",
            password="disabled",
            name="Internal System Account",
            email="system@indi-allsky",
            active=False,
            admin=True,
        )
        db.session.add(system_user)
        db.session.commit()
    return system_user


def test_config_properties_and_accessors(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        cfg_entry = iacu.save("system", "Test properties")

        config = IndiAllSkyConfig()
        assert config.config_id == cfg_entry.id
        assert config.config_level == cfg_entry.level
        assert config.createDate == cfg_entry.createDate
        assert isinstance(config.config, dict)

        # image_folder getter and setter
        config.image_folder = "/tmp/test_images"
        assert config.image_folder == Path("/tmp/test_images")


def test_config_setter_validation(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        config = IndiAllSkyConfigUtil()

        # Invalid configs
        with pytest.raises(ConfigSaveException):
            config.config = {"INDI_SERVER": 123}

        with pytest.raises(ConfigSaveException):
            config.config = {"INDI_SERVER": "localhost", "CCD_CONFIG": "not_a_dict"}

        with pytest.raises(ConfigSaveException):
            config.config = {
                "INDI_SERVER": "localhost",
                "CCD_CONFIG": {},
                "INDI_CONFIG_DEFAULTS": "not_a_dict",
            }

        # Valid config
        valid = {
            "INDI_SERVER": "localhost",
            "CCD_CONFIG": {},
            "INDI_CONFIG_DEFAULTS": {},
        }
        config.config = valid
        assert config.config["INDI_SERVER"] == "localhost"


def test_config_entry_future_timestamp_and_id_lookup(flask_app, db):
    with flask_app.app_context():
        user = ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()

        # Insert future config to trigger future timestamp warning (lines 1000-1001)
        future_date = datetime.now(tz=timezone.utc).replace(tzinfo=None) + timedelta(days=5)
        future_entry = IndiAllSkyDbConfigTable(
            data={"INDI_SERVER": "localhost", "CCD_CONFIG": {}, "INDI_CONFIG_DEFAULTS": {}},
            createDate=future_date,
            level=str(__config_level__),
            user_id=user.id,
            note="Future config",
            encrypted=False,
        )
        db.session.add(future_entry)
        db.session.commit()

        # Lookup with explicit config_id (line 1006)
        entry_by_id = iacu._getConfigEntry(config_id=future_entry.id)
        assert entry_by_id.id == future_entry.id

        # Lookup latest triggers the future config warning
        latest_entry = iacu._getConfigEntry()
        assert latest_entry is not None

        # Clean up future entry
        db.session.delete(future_entry)
        db.session.commit()


def test_config_validation_edge_cases(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()

        # 1. Level 2 key wrong type (lines 1280-1281)
        orig_dict = iacu.config["DEW_HEATER"]
        iacu.config["DEW_HEATER"] = dict(orig_dict)
        iacu.config["DEW_HEATER"]["HOLD_SECONDS"] = "not_an_int"
        with pytest.raises(ConfigSaveException):
            iacu._validateConfig()
        iacu.config["DEW_HEATER"] = orig_dict

        # 2. Level 2 key unknown in base config (line 1283 KeyError)
        iacu.config["FILETRANSFER"] = dict(iacu.config["FILETRANSFER"])
        iacu.config["FILETRANSFER"]["UNKNOWN_SUBKEY"] = "val"
        iacu._validateConfig()
        del iacu.config["FILETRANSFER"]["UNKNOWN_SUBKEY"]

        # 3. Top level key wrong type (lines 1295-1296)
        orig_top = iacu.config["ENCRYPT_PASSWORDS"]
        iacu.config["ENCRYPT_PASSWORDS"] = "not_a_bool"
        with pytest.raises(ConfigSaveException):
            iacu._validateConfig()
        iacu.config["ENCRYPT_PASSWORDS"] = orig_top

        # 4. Top level key unknown in base config (line 1298 KeyError)
        iacu.config["UNKNOWN_TOP_KEY"] = "val"
        iacu._validateConfig()
        del iacu.config["UNKNOWN_TOP_KEY"]


def test_password_encryption_and_decryption_all_fields(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        iacu.config["ENCRYPT_PASSWORDS"] = True

        # Populate all 14 password fields
        iacu.config["FILETRANSFER"]["PASSWORD"] = "ftp_pass"
        iacu.config["S3UPLOAD"]["SECRET_KEY"] = "s3_secret"
        iacu.config["MQTTPUBLISH"]["PASSWORD"] = "mqtt_pub_pass"
        iacu.config["SYNCAPI"]["APIKEY"] = "sync_key"
        iacu.config["ALLSKYMAP"]["API_KEY"] = "map_key"
        iacu.config["PYCURL_CAMERA"]["PASSWORD"] = "pycurl_pass"
        iacu.config["TEMP_SENSOR"]["OPENWEATHERMAP_APIKEY"] = "owm_key"
        iacu.config["TEMP_SENSOR"]["WUNDERGROUND_APIKEY"] = "wu_key"
        iacu.config["TEMP_SENSOR"]["ASTROSPHERIC_APIKEY"] = "astro_key"
        iacu.config["TEMP_SENSOR"]["MQTT_PASSWORD"] = "sensor_mqtt_pass"
        iacu.config["DEVICE"]["MQTT_PASSWORD"] = "device_mqtt_pass"
        iacu.config["LIBCAMERA"]["MQTT_PASSWORD"] = "libcam_mqtt_pass"
        iacu.config["ADSB"]["PASSWORD"] = "adsb_pass"
        iacu.config["IMAGE_OVERLAY"]["A_PASSWORD"] = "overlay_pass"

        # Save with encryption (tests lines 1305-1432 non-empty branches)
        entry = iacu.save("system", "Test encrypted save")
        assert entry.encrypted is True
        assert entry.data["FILETRANSFER"]["PASSWORD"] == ""
        assert entry.data["FILETRANSFER"]["PASSWORD_E"] != ""

        # Load into IndiAllSkyConfig (tests decryption lines 1040-1155 non-empty branches)
        config = IndiAllSkyConfig()
        assert config.config["FILETRANSFER"]["PASSWORD"] == "ftp_pass"
        assert config.config["S3UPLOAD"]["SECRET_KEY"] == "s3_secret"
        assert config.config["MQTTPUBLISH"]["PASSWORD"] == "mqtt_pub_pass"
        assert config.config["SYNCAPI"]["APIKEY"] == "sync_key"
        assert config.config["ALLSKYMAP"]["API_KEY"] == "map_key"
        assert config.config["PYCURL_CAMERA"]["PASSWORD"] == "pycurl_pass"
        assert config.config["TEMP_SENSOR"]["OPENWEATHERMAP_APIKEY"] == "owm_key"
        assert config.config["TEMP_SENSOR"]["WUNDERGROUND_APIKEY"] == "wu_key"
        assert config.config["TEMP_SENSOR"]["ASTROSPHERIC_APIKEY"] == "astro_key"
        assert config.config["TEMP_SENSOR"]["MQTT_PASSWORD"] == "sensor_mqtt_pass"
        assert config.config["DEVICE"]["MQTT_PASSWORD"] == "device_mqtt_pass"
        assert config.config["LIBCAMERA"]["MQTT_PASSWORD"] == "libcam_mqtt_pass"
        assert config.config["ADSB"]["PASSWORD"] == "adsb_pass"
        assert config.config["IMAGE_OVERLAY"]["A_PASSWORD"] == "overlay_pass"


def test_password_encryption_and_decryption_empty_fields_when_encrypted(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        iacu.config["ENCRYPT_PASSWORDS"] = True

        # Clear all 14 password fields
        iacu.config["FILETRANSFER"]["PASSWORD"] = ""
        iacu.config["S3UPLOAD"]["SECRET_KEY"] = ""
        iacu.config["MQTTPUBLISH"]["PASSWORD"] = ""
        iacu.config["SYNCAPI"]["APIKEY"] = ""
        iacu.config["ALLSKYMAP"]["API_KEY"] = ""
        iacu.config["PYCURL_CAMERA"]["PASSWORD"] = ""
        iacu.config["TEMP_SENSOR"]["OPENWEATHERMAP_APIKEY"] = ""
        iacu.config["TEMP_SENSOR"]["WUNDERGROUND_APIKEY"] = ""
        iacu.config["TEMP_SENSOR"]["ASTROSPHERIC_APIKEY"] = ""
        iacu.config["TEMP_SENSOR"]["MQTT_PASSWORD"] = ""
        iacu.config["DEVICE"]["MQTT_PASSWORD"] = ""
        iacu.config["LIBCAMERA"]["MQTT_PASSWORD"] = ""
        iacu.config["ADSB"]["PASSWORD"] = ""
        iacu.config["IMAGE_OVERLAY"]["A_PASSWORD"] = ""

        # Tests lines 1314-1315, 1323-1324, ..., 1431-1432 (empty branches in _encryptPasswords)
        entry = iacu.save("system", "Test encrypted save with empty passwords")
        assert entry.encrypted is True

        # Load into IndiAllSkyConfig (tests lines 1050, 1058, ..., 1154 in _decrypt_passwords)
        config = IndiAllSkyConfig()
        assert config.config["FILETRANSFER"]["PASSWORD"] == ""


def test_password_encryption_and_decryption_unencrypted_and_missing_leaves(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        iacu.config["ENCRYPT_PASSWORDS"] = False

        # Delete leaves so that config.get(leaf) is None in leaf_list loop (tests lines 1191 and 1485)
        del iacu.config["FILETRANSFER"]
        del iacu.config["S3UPLOAD"]

        # Tests unencrypted save (lines 1435-1518 and line 1485)
        cfg, encrypted = iacu._encryptPasswords()
        assert encrypted is False
        assert isinstance(cfg["FILETRANSFER"], dict)
        assert isinstance(cfg["S3UPLOAD"], dict)

        # Tests unencrypted decrypt (lines 1156-1223 and line 1191)
        del cfg["FILETRANSFER"]
        del cfg["S3UPLOAD"]
        iacu._config = cfg
        decrypted = iacu._decrypt_passwords()
        assert isinstance(decrypted["FILETRANSFER"], dict)
        assert isinstance(decrypted["S3UPLOAD"], dict)


def test_config_util_bootstrap_already_initialized(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        # Save a config so it exists
        iacu.save("system", "Existing for bootstrap")

        # Calling bootstrap when config already exists triggers sys.exit(1) (lines 1540-1542)
        with pytest.raises(SystemExit):
            iacu.bootstrap()


def test_config_util_list_and_user_count(flask_app, db, capsys):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        # Ensure at least one config exists to test row formatting in list (line 1568)
        iacu.save("system", "For list test")

        # test list (lines 1556-1570)
        iacu.list()
        captured = capsys.readouterr()
        assert "ID" in captured.out
        assert "Level" in captured.out

        # test user_count (lines 1807-1813)
        iacu.user_count()
        captured = capsys.readouterr()
        assert int(captured.out.strip()) >= 1


def test_config_util_load_variations(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        iacu.save("system", "Initial setup for load")

        # 1. Force=False when config exists -> sys.exit(1) (lines 1582-1588)
        f_mock = io.StringIO("{}")
        f_mock.name = "test.json"
        with pytest.raises(SystemExit):
            iacu.load(config=f_mock, force=False)

        # 2. Force=True with invalid config json -> sys.exit(1) (lines 1601-1603)
        invalid_f = io.StringIO(json.dumps({"INDI_SERVER": 123}))
        invalid_f.name = "invalid.json"
        with pytest.raises(SystemExit):
            iacu.load(config=invalid_f, force=True)

        # 3. Force=True with valid config json -> loads and saves (lines 1606-1609)
        valid_dict = iacu.base_config.copy()
        valid_dict["INDI_SERVER"] = "custom_indi_server"
        valid_f = io.StringIO(json.dumps(valid_dict))
        valid_f.name = "valid.json"
        iacu.load(config=valid_f, force=True)
        latest = iacu._getConfigEntry()
        assert latest.data["INDI_SERVER"] == "custom_indi_server"

        # 4. Force=False when NO config exists in DB -> NoResultFound caught (line 1590) and loads
        valid_f2 = io.StringIO(json.dumps(valid_dict))
        valid_f2.name = "valid2.json"
        with patch.object(iacu, "_getConfigEntry", side_effect=NoResultFound):
            iacu.load(config=valid_f2, force=False)


def test_config_util_update_level_no_result(flask_app, db):
    with flask_app.app_context():
        iacu = IndiAllSkyConfigUtil()
        # Mock _getConfigEntry to raise NoResultFound (lines 1621-1623)
        with patch.object(iacu, "_getConfigEntry", side_effect=NoResultFound):
            with pytest.raises(SystemExit):
                iacu.update_level()


def test_config_util_edit_variations(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()

        # 1. NoResultFound -> sys.exit(1) (lines 1640-1642)
        with patch.object(iacu, "_getConfigEntry", side_effect=NoResultFound):
            with pytest.raises(SystemExit):
                iacu.edit()

        # Save config in DB so edit can read it
        iacu.save("system", "Edit test initial config")

        # 2. File mtime unchanged -> logs "Config not updated" (lines 1676-1679)
        with patch("os.system", return_value=0):
            iacu.edit()

        # 3. File updated with invalid JSON then valid JSON (lines 1671-1673 and 1682-1687)
        attempts = 0

        def fake_editor(cmd):
            nonlocal attempts
            attempts += 1
            filename = cmd.split("editor ")[1]
            if attempts == 1:
                # write invalid JSON first to trigger JSONDecodeError
                with open(filename, "w") as f:
                    f.write("INVALID JSON {{{")
            else:
                # write valid JSON and modify mtime
                updated = iacu.base_config.copy()
                updated["INDI_SERVER"] = "edited_server"
                with open(filename, "w") as f:
                    json.dump(updated, f)
                new_time = time.time() + 100
                os.utime(filename, (new_time, new_time))

        with patch("os.system", side_effect=fake_editor), patch("time.sleep", return_value=None):
            iacu.edit()

        latest = iacu._getConfigEntry()
        assert latest.data["INDI_SERVER"] == "edited_server"


def test_config_util_revert_variations(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        cfg_entry = iacu.save("system", "Initial setup for revert")

        # 1. Config ID not found -> sys.exit(1) (lines 1700-1702)
        with pytest.raises(SystemExit):
            iacu.revert(config_id=99999999)

        # 2. User confirms 'n' -> sys.exit(1) (lines 1706-1708)
        with patch("builtins.input", return_value="n"):
            with pytest.raises(SystemExit):
                iacu.revert(config_id=cfg_entry.id)

        # 3. User confirms 'y' -> reverts and saves (lines 1711-1715)
        with patch("builtins.input", return_value="y"):
            iacu.revert(config_id=cfg_entry.id)


def test_config_util_dump_and_dumpfile_variations(flask_app, db, capsys, tmp_path):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()
        cfg_entry = iacu.save("system", "Initial setup for dump")

        # dump: not found (lines 1727-1729)
        with pytest.raises(SystemExit):
            iacu.dump(config_id=99999999)

        # dump: success (lines 1731-1737)
        iacu.dump(config_id=cfg_entry.id)
        captured = capsys.readouterr()
        assert "INDI_SERVER" in captured.out

        # dumpfile: empty outfile (lines 1749-1751)
        with pytest.raises(SystemExit):
            iacu.dumpfile(config_id=cfg_entry.id, outfile="")

        # dumpfile: not found (lines 1756-1758)
        with pytest.raises(SystemExit):
            iacu.dumpfile(config_id=99999999, outfile=str(tmp_path / "out.json"))

        # dumpfile: PermissionError (lines 1775-1777)
        with patch("io.open", side_effect=PermissionError("Permission denied")):
            with pytest.raises(SystemExit):
                iacu.dumpfile(config_id=cfg_entry.id, outfile=str(tmp_path / "perm.json"))

        # dumpfile: success (lines 1767-1774)
        out_target = tmp_path / "valid_dump.json"
        iacu.dumpfile(config_id=cfg_entry.id, outfile=str(out_target))
        assert out_target.exists()
        content = json.loads(out_target.read_text())
        assert "INDI_SERVER" in content


def test_config_util_delete_variations(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()

        # 1. Config ID not found -> sys.exit(1) (lines 1790-1792)
        with pytest.raises(SystemExit):
            iacu.delete(config_id=99999999)

        # Create an extra config entry to test deletion
        cfg_to_delete = iacu.save("system", "Config to delete")

        # 2. User confirms 'n' -> sys.exit(1) (lines 1796-1798)
        with patch("builtins.input", return_value="n"):
            with pytest.raises(SystemExit):
                iacu.delete(config_id=cfg_to_delete.id)

        # 3. User confirms 'y' -> deletes config (lines 1801-1803)
        with patch("builtins.input", return_value="y"):
            iacu.delete(config_id=cfg_to_delete.id)

        assert IndiAllSkyDbConfigTable.query.filter_by(id=cfg_to_delete.id).first() is None


def test_config_util_flush_variations(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()

        # 1. Confirm 1 != 'y' -> sys.exit(1) (lines 1823-1825)
        with patch("builtins.input", return_value="n"):
            with pytest.raises(SystemExit):
                iacu.flush()

        # 2. Confirm 2 != 'n' -> sys.exit(1) (lines 1828-1830)
        with patch("builtins.input", side_effect=["y", "y"]):
            with pytest.raises(SystemExit):
                iacu.flush()

        # 3. Confirm 3 incorrect number -> sys.exit(1) (lines 1834-1836)
        with patch("builtins.input", side_effect=["y", "n", "wrong_number"]), patch("random.randint", return_value=1234):
            with pytest.raises(SystemExit):
                iacu.flush()

        # 4. All confirmations pass -> flushes configs (lines 1838-1842)
        with patch("builtins.input", side_effect=["y", "n", "4321"]), patch("random.randint", return_value=1234):
            iacu.flush()
            assert IndiAllSkyDbConfigTable.query.count() == 0


def test_config_util_create_system_account_existing(flask_app, db):
    with flask_app.app_context():
        ensure_system_user(db)
        iacu = IndiAllSkyConfigUtil()

        # Line 1851: system user already exists -> returns it
        sys_user = iacu._createSystemAccount()
        assert sys_user.username == "system"
