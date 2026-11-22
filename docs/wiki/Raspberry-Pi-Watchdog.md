# Hardware Watchdog Integration

A hardware watchdog operates as a fail-safe timer ("dead man's switch"). The hardware counter counts down continuously; if the kernel or software freezes and fails to send a periodic heartbeat signal, the timer elapses and triggers an immediate physical hardware reboot.

This ensures remote, unmonitored allsky camera systems recover autonomously from kernel panics, memory exhaustion (OOM), or hardware bus lockups.

---

## 1. Systemd Watchdog Configuration

Modern Linux distributions manage the hardware watchdog device directly via systemd's PID 1 supervisor.

Create the watchdog configuration drop-in at `/etc/systemd/system.conf.d/indi-allsky-watchdog.conf`:

```bash
sudo mkdir -p /etc/systemd/system.conf.d
sudo tee /etc/systemd/system.conf.d/indi-allsky-watchdog.conf <<'EOF'
[Manager]
# Hardware watchdog timeout (reboots system if pinged < every 15s)
RuntimeWatchdogSec=15
# Extended watchdog timeout during system shutdown/reboot cycles
ShutdownWatchdogSec=10min
EOF
```

---

## 2. Hardware Module Enablement

### Raspberry Pi (Broadcom SoC)
Verify that the hardware watchdog device tree parameter is enabled in `/boot/firmware/config.txt` (or `/boot/config.txt` on older distributions):
```ini
dtparam=watchdog=on
```

Reboot the system to load the watchdog kernel driver:
```bash
sudo reboot
```

---

## 3. Verification & Testing

### Verify Active Watchdog Configuration
Confirm systemd has initialized the hardware timer:
```bash
systemctl show | grep -i watchdog
```
Expected output:
```text
RuntimeWatchdogUSec=15s
RebootWatchdogUSec=10min
KExecWatchdogUSec=0
ShutdownWatchdogUSec=10min
```

### Trace Watchdog Heartbeats
Verify that systemd (PID 1) is actively sending keepalive `ioctl` pings to `/dev/watchdog`:
```bash
sudo strace -t -e ioctl -p 1 2>&1 | grep WDIOC_KEEPALIVE
```
Expected output:
```text
12:00:05 ioctl(9, WDIOC_KEEPALIVE) = 0
12:00:10 ioctl(9, WDIOC_KEEPALIVE) = 0
12:00:15 ioctl(9, WDIOC_KEEPALIVE) = 0
```