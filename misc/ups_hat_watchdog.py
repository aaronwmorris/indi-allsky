#!/usr/bin/env python3
import json
import os
from pathlib import Path
import tempfile
import time
import subprocess
import logging


# UPS HAT (E) MCU
I2C_BUS = 1
ADDR = 0x2D

# ======== Your cells / policy ========
# 4S Li-Ion 21700: good practical shutdown threshold
LOW_CELL_MV = 3150			# shutdown if min cell below this for long enough
INTERVAL_S = 2				# sampling interval
TRIP_COUNT = 30				# 30*2s = 60s persistence required

# optional: avoid shutdown while actively charging
BIT_FAST = 0x40
BIT_CHG  = 0x80
BIT_DIS  = 0x20

LOG = logging.getLogger("ups_hat_watchdog")
STATUS_FILE = Path('/run/indi-allsky-ups-watchdog/health.json')


def u16(lo, hi):
	return lo | (hi << 8)


def s16(lo, hi):
	v = u16(lo, hi)
	if v & 0x8000:
		v -= 0x10000
	return v


def read_register(bus, register, size):
	d = bus.read_i2c_block_data(ADDR, register, size)
	if len(d) != size:
		raise ValueError("Incomplete UPS register read")
	return d


def read_status(bus):
	b = read_register(bus, 0x02, 1)[0]
	if b == 0xff:
		raise ValueError('Invalid UPS status byte')
	if b & BIT_FAST:
		return "fast_charging"
	if b & BIT_CHG:
		return "charging"
	if b & BIT_DIS:
		return "discharge"
	return "idle"


def read_batt_current_ma(bus):
	# Battery current is signed at 0x22/0x23 (from Waveshare register map)
	d = read_register(bus, 0x22, 2)
	return s16(d[0], d[1])


def read_cells_mv(bus):
	d = read_register(bus, 0x30, 8)
	c1 = u16(d[0], d[1])
	c2 = u16(d[2], d[3])
	c3 = u16(d[4], d[5])
	c4 = u16(d[6], d[7])
	cells = (c1, c2, c3, c4)
	# A missing cell / uninitialized register must not vote for shutdown.
	if not all(0 < mv <= 5000 for mv in cells):
		raise ValueError("Invalid UPS cell voltage")
	return cells


def arm_poweron_when_charged(bus):
	# Waveshare example: write 0x55 to reg 0x01
	try:
		bus.write_byte_data(ADDR, 0x01, 0x55)
		LOG.info("Wrote 0x55 to reg 0x01 (power-on when charged).")
	except Exception as e:
		LOG.warning("Failed to write reg 0x01: %s", str(e))


def report(path, readable, last_good, last_good_mono):
	try:
		path.parent.mkdir(mode=0o755, exist_ok=True)
		with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
			tmp = Path(f.name)
			try:
				json.dump(dict(readable=readable, last_good=last_good, last_good_mono=last_good_mono), f)
				f.flush()
				os.fchmod(f.fileno(), 0o644)
				os.replace(tmp, path)
			finally:
				tmp.unlink(missing_ok=True)
	except OSError as e:
		# Monitoring the status file must never interrupt battery protection.
		LOG.warning("Cannot publish UPS status: %s", e)


def watch(bus_factory, poweroff, status_path=STATUS_FILE):
	low = 0
	failures = 0
	last_good = last_good_mono = 0
	bus = None
	report(status_path, False, last_good, last_good_mono)
	try:
		while True:
			try:
				if bus is None:
					bus = bus_factory(I2C_BUS)
				state = read_status(bus)
				ibat = read_batt_current_ma(bus)
				cells = read_cells_mv(bus)
			except (OSError, ValueError, RuntimeError) as e:
				low = 0
				failures += 1
				LOG.warning("USV nicht auslesbar: %s (last valid sample: %s)", e, last_good or "none")
				report(status_path, False, last_good, last_good_mono)
				if bus is not None and failures >= 3:
					# Close this service's file descriptor only.
					bus.close()
					bus = None
					failures = 0
				time.sleep(INTERVAL_S)
				continue

			failures = 0
			last_good = int(time.time())
			last_good_mono = time.monotonic()
			report(status_path, True, last_good, last_good_mono)
			min_cell = min(cells)
			LOG.info("state=%s ibat=%dmA cells=%s min_cell=%dmV low_count=%d",
				state, ibat, cells, min_cell, low)
			if min_cell < LOW_CELL_MV and state in ("discharge", "idle"):
				low += 1
				LOG.warning("LOW CELL (min=%dmV). Shutdown in ~%ds if persists.",
					min_cell, max(0, TRIP_COUNT - low) * INTERVAL_S)
				if low >= TRIP_COUNT:
					LOG.error("Triggering graceful shutdown now.")
					arm_poweron_when_charged(bus)
					poweroff()
					return
			else:
				low = 0
			time.sleep(INTERVAL_S)
	finally:
		if bus is not None:
			bus.close()


def main():
	from smbus2 import SMBus

	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	LOG.info("UPS Watchdog started: low_cell=%dmV interval=%ds trip=%d (~%ds)",
		LOW_CELL_MV, INTERVAL_S, TRIP_COUNT, INTERVAL_S * TRIP_COUNT)
	watch(SMBus, lambda: subprocess.run(["/usr/bin/systemctl", "poweroff"], check=False))


if __name__ == "__main__":
	main()
