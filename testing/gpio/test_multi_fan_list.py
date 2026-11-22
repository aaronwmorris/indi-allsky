from multiprocessing import Array, Queue
from pathlib import Path
import unittest
from unittest.mock import patch

from indi_allsky import constants
from indi_allsky.sensor import SensorWorker, get_fan_configs, normalize_fan_config


class _FakeFanDevice:
    def __init__(self, config, **_kwargs):
        self.config = config
        self._state = -1
        self.deinit_called = False

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = int(value)

    def deinit(self):
        self.deinit_called = True


class TestMultiFanList(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[2]

    def _make_worker(self, config):
        sensors_temp_av = Array('d', [0.0] * 10)
        sensors_user_av = Array('d', [0.0] * 60)
        astro_av = Array('d', [0.0] * 10)
        night_av = Array('i', [0, 0])
        return SensorWorker(
            1,
            config,
            Queue(),
            Queue(),
            sensors_temp_av,
            sensors_user_av,
            astro_av,
            night_av,
        )

    def test_get_fan_configs_legacy_and_multi(self):
        legacy_cfg = {'FAN': {'CLASSNAME': 'fan_simulator', 'TARGET': 25.0}}
        self.assertEqual(len(get_fan_configs(legacy_cfg)), 1)

        multi_cfg = {
            'FAN': {'CLASSNAME': 'fan_simulator', 'TARGET': 25.0},
            'FANS': [
                {'CLASSNAME': 'fan_simulator', 'TARGET': 45.0, 'TEMP_USER_VAR_SLOT': 'sensor_user_11'},
                {'CLASSNAME': 'fan_simulator', 'TARGET': 55.0, 'TEMP_USER_VAR_SLOT': 'sensor_user_12'},
            ],
        }
        cfgs = get_fan_configs(multi_cfg)
        self.assertEqual(len(cfgs), 3)
        norm = normalize_fan_config(cfgs[1])
        self.assertEqual(norm['TARGET'], 45.0)
        self.assertEqual(norm['TEMP_USER_VAR_SLOT'], 'sensor_user_11')

    def test_three_fans_independent_thresholds(self):
        config = {
            'TEMP_DISPLAY': 'c',
            'FAN': {
                'CLASSNAME': 'fan_simulator',
                'ENABLE_NIGHT': True,
                'THOLD_ENABLE': True,
                'TARGET': 30.0,
                'TEMP_USER_VAR_SLOT': 'sensor_user_10',
                'LEVEL_DEF': 0,
                'LEVEL_LOW': 33,
                'LEVEL_MED': 66,
                'LEVEL_HIGH': 100,
                'THOLD_DIFF_LOW': -10,
                'THOLD_DIFF_MED': -5,
                'THOLD_DIFF_HIGH': 0,
                'HOLD_SECONDS': 0,
            },
            'FANS': [
                {
                    'CLASSNAME': 'fan_simulator',
                    'ENABLE_NIGHT': True,
                    'THOLD_ENABLE': True,
                    'TARGET': 50.0,
                    'TEMP_USER_VAR_SLOT': 'sensor_user_11',
                    'LEVEL_DEF': 0,
                    'LEVEL_LOW': 40,
                    'LEVEL_MED': 70,
                    'LEVEL_HIGH': 100,
                    'THOLD_DIFF_LOW': -10,
                    'THOLD_DIFF_MED': -5,
                    'THOLD_DIFF_HIGH': 0,
                    'HOLD_SECONDS': 0,
                },
                {
                    'CLASSNAME': 'fan_simulator',
                    'ENABLE_NIGHT': False,
                    'THOLD_ENABLE': True,
                    'TARGET': 20.0,
                    'TEMP_USER_VAR_SLOT': 'sensor_user_12',
                    'LEVEL_DEF': 10,
                    'LEVEL_LOW': 25,
                    'LEVEL_MED': 50,
                    'LEVEL_HIGH': 100,
                    'THOLD_DIFF_LOW': -10,
                    'THOLD_DIFF_MED': -5,
                    'THOLD_DIFF_HIGH': 0,
                    'HOLD_SECONDS': 0,
                },
            ],
        }

        worker = self._make_worker(config)
        worker.init_gpio()
        worker.init_dew_heater()
        with patch('indi_allsky.sensor.fans.fan_simulator', _FakeFanDevice):
            worker.init_fans()
        self.assertEqual(len(worker.fans), 3)

        worker.sensors_user_av[constants.SENSOR_INDEX_MAP['sensor_user_10']] = 32.0  # > 30 + 0 -> high (100)
        worker.sensors_user_av[constants.SENSOR_INDEX_MAP['sensor_user_11']] = 46.0  # delta -4 (> -5) -> med (70)
        worker.sensors_user_av[constants.SENSOR_INDEX_MAP['sensor_user_12']] = 25.0  # > 20 + 0 -> high (100) during day

        worker.night = False
        worker.check_fan_thresholds()

        self.assertEqual(worker.fans[0]['device'].state, 100)
        self.assertEqual(worker.fans[1]['device'].state, 70)
        self.assertEqual(worker.fans[2]['device'].state, 100)
        self.assertEqual(worker.sensors_user_av[constants.SENSOR_USER_FAN_LEVEL], 100.0)

        # At night, fan 3 has ENABLE_NIGHT=False so night_day_change turns it off
        worker.night = True
        worker.night_day_change()
        self.assertEqual(worker.fans[2]['device'].state, 0)

        for entry in worker.fans:
            entry['device'].deinit()
            self.assertTrue(entry['device'].deinit_called)

    def test_default_config_and_templates(self):
        config_py = (self.project_root / 'indi_allsky' / 'config.py').read_text(encoding='utf-8')
        self.assertIn('"FANS" : [],', config_py)

        devices_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'config' / 'devices.html').read_text(encoding='utf-8')
        config_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'config.html').read_text(encoding='utf-8')
        self.assertIn('collectAdditionalFans', devices_html)
        self.assertIn('collectAdditionalFans', config_html)


if __name__ == '__main__':
    unittest.main()
