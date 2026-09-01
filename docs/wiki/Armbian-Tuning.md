# Overview
Armbian uses a few optimizations to reduce writes to the SDcard such as zram and zlog.  These need to be disabled to have enough space to build the python module packages.

Once indi-allsky is built and running, these services can be re-enabled.

## tmpfs
* Edit ```/etc/fstab```
* Comment out the /tmp mount

## ramlog
* Edit ```/etc/default/armbian-ramlog```
* Set ```ENABLED=false```

## zram
* Edit ```/etc/default/armbian-zram-config```
* Set ```ENABLED=false```

## Install dphys-swapfile
```
sudo apt-get install dphys-swapfile
```

REBOOT!