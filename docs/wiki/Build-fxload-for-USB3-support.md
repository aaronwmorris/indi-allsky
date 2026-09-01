# General
fxload under Debian does not support USB3 (fx3) targets.  A newer version of fxload needs to be compiled from source.

This primarily affects QHY USB3 cameras.


## Instructions
* Install supporting packages

      sudo apt-get install automake libtool libudev-dev build-essential git

* Clone libusb

      git clone https://github.com/libusb/libusb

* Build libusb main

      cd libusb

      ./autogen.sh
      ./configure --prefix=/usr/local
      make
        
      sudo make install

* Build examples

      cd examples
      make

* Install fxload

      sudo install -o root -g root -m 755 ./.libs/fxload /usr/local/sbin


## Find the QHY firmware loader device
The device is normally a `Cypress WestBridge` device

    $ lsusb
    Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
    Bus 001 Device 003: ID 1618:0485 Cypress WestBridge    <---- THIS IS THE FIRMWARE LOADER
    Bus 001 Device 002: ID 2109:3431 VIA Labs, Inc. Hub
    Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub


## Manual firmware load
You will need to pick the correct firmware file for your camera model and the USB device ID.

    sudo LD_LIBRARY_PATH=/usr/local/lib /usr/local/sbin/fxload -t fx3 -I /lib/firmware/qhy/QHY5III485.img -d 1618:0485

This should show the following:
```
microcontroller type: fx3
/lib/firmware/qhy/QHY5III485.img: type Cypress IMG format
open firmware image /lib/firmware/qhy/QHY5III485.img for RAM upload
normal FW binary executable image with checksum
FX3 bootloader version: 0x000000A9
writing image...
transfer execution to Program Entry at 0x40014984
```

## Automatic firmware load

* Setup new custom rules
```
sudo tee /etc/udev/rules.d/99-qhyccd_custom.rules <<EOF
ACTION!="add", GOTO="qhy_end_new"
SUBSYSTEM!="usb", GOTO="qhy_end_new"

ATTRS{idVendor}=="1618", ATTRS{idProduct}=="0485", ENV{LD_LIBRARY_PATH}="/usr/local/lib", RUN+="/usr/local/sbin/fxload -t fx3 -I /lib/firmware/qhy/QHY5III485.img -d 1618:0485"

ATTRS{idVendor}=="1618", MODE="0666"

LABEL="qhy_end_new"
EOF
```

* Dynamically reload udev rules
```
sudo udevadm control --reload-rules
sudo udevadm trigger

```