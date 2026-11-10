import json


from indi_allsky.sensor_health import ups_problem
from misc import ups_hat_watchdog as monitor


class Bus:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.closed = False
        self.commands = []

    def read_i2c_block_data(self, addr, register, length):
        if register == 0x02:
            self.cell_mv, self.charge = next(self.rows)
            return [0x80 if self.charge else 0x20]
        if register == 0x22:
            return [0, 0]
        if self.cell_mv is None:
            return [0, 1]    # short read
        return [self.cell_mv & 255, self.cell_mv >> 8] * 4

    def close(self):
        self.closed = True

    def write_byte_data(self, *args):
        self.commands.append(args)


def test_damaged_reads_break_low_voltage_sequence_and_reopen_only_own_bus(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, 'TRIP_COUNT', 3)
    file = tmp_path/'health.json'
    first = Bus([(3100, False), (3100, False), (0, False), (65535, False), (None, False)])
    second = Bus([(3100, False), (3100, True), (3100, False), (3100, False), (3100, False)])
    devices = iter([first, second])
    observed = []
    shutdown = []
    monkeypatch.setattr(monitor.time, 'sleep', lambda seconds: observed.append(json.loads(file.read_text())))
    monitor.watch(lambda n: next(devices), lambda: shutdown.append(True), file)
    assert shutdown == [True] and first.closed and second.closed
    assert first.commands == [] and second.commands == [(0x2D, 1, 0x55)]
    assert [row['readable'] for row in observed] == [True, True, False, False, False, True, True, True, True]
    assert observed[1]['last_good_mono'] == observed[4]['last_good_mono']
    assert not ups_problem(file)
    assert ups_problem(file, json.loads(file.read_text())['last_good_mono'] + 16)


def test_absent_optional_ups_is_not_an_error(tmp_path):
    path = tmp_path / 'absent'
    assert not ups_problem(path)
    path.write_text('{broken')
    assert ups_problem(path)
