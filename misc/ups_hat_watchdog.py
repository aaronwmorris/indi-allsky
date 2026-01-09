#!/usr/bin/env python3
import time
import subprocess
import logging
from smbus2 import SMBus

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


def u16(lo, hi):
	return lo | (hi << 8)


def s16(lo, hi):
	v = u16(lo, hi)
	if v & 0x8000:
		v -= 0x10000
	return v


def read_status(bus):
	b = bus.read_i2c_block_data(ADDR, 0x02, 1)[0]
	if b & BIT_FAST:
		return "fast_charging"
	if b & BIT_CHG:
		return "charging"
	if b & BIT_DIS:
		return "discharge"
	return "idle"


def read_batt_current_ma(bus):
	# Battery current is signed at 0x22/0x23 (from Waveshare register map)
	d = bus.read_i2c_block_data(ADDR, 0x22, 2)
	return s16(d[0], d[1])


def read_cells_mv(bus):
	d = bus.read_i2c_block_data(ADDR, 0x30, 8)
	c1 = u16(d[0], d[1])
	c2 = u16(d[2], d[3])
	c3 = u16(d[4], d[5])
	c4 = u16(d[6], d[7])
	return (c1, c2, c3, c4)


def arm_poweron_when_charged(bus):
	# Waveshare example: write 0x55 to reg 0x01
	try:
		bus.write_byte_data(ADDR, 0x01, 0x55)
		LOG.info("Wrote 0x55 to reg 0x01 (power-on when charged).")
	except Exception as e:
		LOG.warning("Failed to write reg 0x01: %s", str(e))


def main():
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	LOG.info("UPS Watchdog started: low_cell=%dmV interval=%ds trip=%d (~%ds)",
		LOW_CELL_MV, INTERVAL_S, TRIP_COUNT, INTERVAL_S * TRIP_COUNT)

	low = 0

	with SMBus(I2C_BUS) as bus:
		while True:
			try:
				state = read_status(bus)
				ibat = read_batt_current_ma(bus)
				cells = read_cells_mv(bus)
				min_cell = min(cells)

				LOG.info("state=%s ibat=%dmA cells=%s min_cell=%dmV low_count=%d",
					state, ibat, cells, min_cell, low)

				# Only shutdown if not charging (discharge/idle)
				not_charging = (state in ("discharge", "idle"))

				if (min_cell < LOW_CELL_MV) and not_charging:
					low += 1
					remaining = max(0, (TRIP_COUNT - low) * INTERVAL_S)
					LOG.warning("LOW CELL (min=%dmV). Shutdown in ~%ds if persists.", min_cell, remaining)

					if low >= TRIP_COUNT:
						LOG.error("Triggering graceful shutdown now.")
						arm_poweron_when_charged(bus)
						subprocess.run(["/usr/bin/systemctl", "poweroff"], check=False)
						return
				else:
					low = 0

			except Exception as e:
				LOG.warning("Read error: %s", str(e))
				low = 0

			time.sleep(INTERVAL_S)


if __name__ == "__main__":
	main()
