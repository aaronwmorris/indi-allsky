# General
These instructions are mainly for Raspberry PI hardware.  If your hardware has 4GB of memory, decreasing swappiness is probably the only useful optimization.  All of the optimizations are recommended for 1GB systems.

## Decrease swappiness
This will decrease the rate at which the Linux kernel will swap out memory pages to the swap file and reduce disk I/O.
```bash
echo "vm.swappiness = 1" | sudo tee /etc/sysctl.d/90-indi-allsky.conf

sudo sysctl --system
```

### Armbian swappiness
The swappiness setting may have to be commented out in ```/etc/sysctl.conf```

## Increase Swap space

### Trixie
* Edit `/etc/rpi/swap.conf`
```
[Main]
Mechanism=swapfile

[File]
FixedSizeMiB=2048
```

### Bookworm
* Edit `/etc/dphys-swapfile`
* Set `CONF_SWAPSIZE=512` to increase to 512MB
```bash
sudo dphys-swapfile swapoff
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### Armbian swap
* /etc/default/armbian-zram-config

## Decrease video ram
* sudo raspi-config
    * 4 Performance Options -> P2 GPU Memory
    * Set memory to 16MB
        * Note: libcamera requires at least 32MB GPU memory for imx477 and imx378
* Reboot

## Disable GUI
```bash
sudo systemctl set-default multi-user.target

reboot
``` 
