# GPSd & NTP Time Synchronization

Accurate system time is critical for allsky camera operation: solar, lunar, and planetary ephemeris calculations, coordinate transformations, and satellite pass tracking depend upon precise UTC timestamps.

For remote observatories without reliable internet connectivity, a USB or serial GPS/GNSS receiver paired with `gpsd` and `ntpsec` provides stratum-1 time synchronization.

---

## 1. Install & Configure `gpsd`

Ensure your USB GPS receiver (e.g. u-blox, MediaTek) is connected to the host system.

### Debian Package (`.deb`) Installations
```bash
sudo indi-allsky-ctl setup-gps
```

### Source / Git (`setup.sh`) Installations
```bash
./misc/setup_gpsd.sh
```

The script automatically detects the GPS serial port, installs `gpsd` and diagnostic utilities (`gpsd-clients`), configures `/etc/default/gpsd`, and enables the systemd service.

### Verify GPS Reception
Test satellite fix and NMEA sentences using `cgps` or `gpsmon`:
```bash
cgps -s
```

---

## 2. Configure NTP Time Synchronization (`ntpsec`)

To sync the Linux kernel system clock directly from GPS shared memory (SHM):

### Install `ntpsec`
```bash
sudo apt-get install -y ntpsec
```

### Configure NTP Shared Memory Driver
Edit `/etc/ntpsec/ntp.conf`:

```ini
# Shared Memory driver (unit 0) for GPSD
server 127.127.28.0 minpoll 4 maxpoll 4 prefer
fudge 127.127.28.0 refid GPS stratum 1

# If operating completely offline without internet fallback NTP pools:
tos minclock 1 minsane 1
```

Restart the time service:
```bash
sudo systemctl restart ntpsec
```

---

## 3. Validation

Query NTP synchronization status with `ntpq`:
```bash
ntpq -p
```

Expected output format:
```text
     remote           refid      st t when poll reach   delay   offset   jitter
===============================================================================
*xSHM(0)          .GPS.            1 l   14   16  377   0.0000   0.0242   0.8120
+time.cloudflare. 10.0.0.1         3 u   97 1024  377  12.1493   1.4558   0.8710
```
An asterisk (`*`) or plus (`+`) alongside `SHM(0)` indicates the kernel clock is actively synchronizing with the GPS receiver.