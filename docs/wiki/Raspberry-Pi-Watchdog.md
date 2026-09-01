# Overview
A watchdog is usually a piece of hardware that has the ability to reset or power-cycle equipment that stops responding, in effect a `Dead Man's Switch`.  Using a watchdog needs two components:

1. The hardware watchdog
1. Software that sends the heartbeat signal

The watchdog hardware has an internal timer that will reset the system if it is allowed to reach the end.  The software continually sends a heartbeat signal to indicate the system is still working.  If the software ever stops sending the signal, or slows down enough, the watchdog will intervene.

# Hardware Support
Raspberry Pi (and almost all single board computers) have native watchdog capabilities.

Many PCs including NUCs also have watchdog capabilities.  The instructions below should work on most systems.

## Setup
As root, create /etc/systemd/system.conf.d

```bash
sudo mkdir /etc/systemd/system.conf.d
```

Create /etc/systemd/system.conf.d/indi-allsky-watchdog.conf
```bash
sudo tee /etc/systemd/system.conf.d/indi-allsky-watchdog.conf <<EOF
[Manager]
RuntimeWatchdogSec=10
ShutdownWatchdogSec=10min 
EOF

```

Reboot!

## Validate
### Settings
```
systemctl show | grep -i watchdog
```

### Operation
Run this command to trace the actual watchdog keepalive.

```bash
$ sudo strace -t -e ioctl -p 1 | grep WDIOC_KEEPALIVE

strace: Process 1 attached
19:50:23 ioctl(9, WDIOC_KEEPALIVE)      = 0
19:50:28 ioctl(9, WDIOC_KEEPALIVE)      = 0
19:50:33 ioctl(9, WDIOC_KEEPALIVE)      = 0
```