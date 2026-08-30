# General

While you can sync time within indi-allsky, it is much better to just let ntpd handle time sync itself with a GPS module.


## Install gpsd
Ensure your GPS adapter is plugged in.

```
./misc/setup_gpsd.sh
```

# Optional
Install ntpsec if you want to perform time synchronization using GPS.

## Install ntpsec
```
sudo apt-get install ntpsec
```

## Configure

Add the following to `/etc/ntpsec/ntp.conf`

```
### The magic pseudo-IP address 127.127.28.0 identifies unit 0 of the ntpd shared-memory driver (NTP0)
server 127.127.28.0 minpoll 4 maxpoll 4 prefer
fudge 127.127.28.0 refid GPS stratum 1

### PPS Kernel mode
#server 127.127.22.0 minpoll 4 maxpoll 4
#fudge 127.127.22.0 flag3 1 refid PPS

### Uncomment if not connected to Internet.  ntp normally requires multiple time sources.
### If you only have GPS connectivity, you must reduce the minimum number of sane time sources to 1.
#tos minclock 1 minsane 1
```

## Validation

Use `ntpq -p` to validate time is syncing from GPS.

The output should look something like this.  The `xSHM(0)` source is the shared memory connection to the GPS device.
```
$ ntpq -p
     remote                                   refid      st t when poll reach   delay   offset   jitter
=======================================================================================================
xSHM(0)                                  .GPS.            1 l   14   16  377   0.0000 -67.2402   1.5992
 0.ubuntu.pool.ntp.org                   .POOL.          16 p    -   64    0   0.0000   0.0000   0.0005
 1.ubuntu.pool.ntp.org                   .POOL.          16 p    -   64    0   0.0000   0.0000   0.0005
 2.ubuntu.pool.ntp.org                   .POOL.          16 p    -  256    0   0.0000   0.0000   0.0005
 3.ubuntu.pool.ntp.org                   .POOL.          16 p    -  256    0   0.0000   0.0000   0.0005
-alphyn.canonical.com                    132.163.96.1     2 u   97 1024  377  50.1493   7.4558   1.8710
+149.28.61.105.vultrusercontent.com      208.113.130.146  3 u  394 1024  377  43.2707   6.7218   1.7831
*99-28-14-242.lightspeed.iplsin.sbcgloba ....             1 u  563 1024  375  50.5627   1.4358   3.8964
+time.tritan.host                        169.117.81.12    2 u  304 1024  377  39.0295   6.4774   2.1746
-pool-173-71-68-71.cmdnnj.fios.verizon.n .PPS.            1 u  248 1024  377  53.3408  11.5682   3.6370
-ntp4.glypnod.com                        129.6.15.27      2 u  431 1024  377  60.4248   8.4087   1.1600
```