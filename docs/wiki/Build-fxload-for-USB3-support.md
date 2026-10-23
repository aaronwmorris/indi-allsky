# Building FX3-Compatible fxload for QHY USB3 Cameras

The standard `fxload` package provided by Debian and Ubuntu repositories only supports Cypress EZ-USB FX and FX2 (USB 2.0) microcontrollers. Many modern astronomical cameras—specifically QHY USB 3.0 models such as the QHY5III series—utilize the Cypress EZ-USB FX3 (CYUSB3014) controller.

Without FX3 firmware loading capability, these cameras remain stuck in bootloader state (`Cypress WestBridge`) upon connection and are not recognized by the `indi_qhy_ccd` driver.

---

## 1. Prerequisites and Compilation

Compile the updated `fxload` tool from the official `libusb` source repository:

```bash
# Install compilation prerequisites
sudo apt-get update
sudo apt-get install -y automake libtool libudev-dev build-essential git

# Clone libusb and compile with local prefix
git clone https://github.com/libusb/libusb.git /tmp/libusb
cd /tmp/libusb

./autogen.sh
./configure --prefix=/usr/local
make -j$(nproc)
sudo make install

# Compile the fxload utility included in libusb examples
cd examples
make fxload

# Install fxload into /usr/local/sbin
sudo install -o root -g root -m 755 .libs/fxload /usr/local/sbin/fxload
```

---

## 2. Identify the Cypress Bootloader Device

Execute `lsusb` to verify that the camera is in Cypress bootloader mode:

```bash
lsusb
```

Example output:
```text
Bus 002 Device 003: ID 1618:0485 Cypress WestBridge
```

* Vendor ID: `1618` (QHYCCD)
* Product ID: `0485` (Cypress FX3 Bootloader)

---

## 3. Firmware Verification

Firmware binary images are typically bundled in `/lib/firmware/qhy/` (installed with QHY INDI drivers or `qhyccd` libraries). Identify the exact `.img` file matching your camera model (e.g., `/lib/firmware/qhy/QHY5III485.img`).

Test loading manually:
```bash
sudo LD_LIBRARY_PATH=/usr/local/lib /usr/local/sbin/fxload -t fx3 -I /lib/firmware/qhy/QHY5III485.img -d 1618:0485
```

Expected output:
```text
microcontroller type: fx3
/lib/firmware/qhy/QHY5III485.img: type Cypress IMG format
open firmware image /lib/firmware/qhy/QHY5III485.img for RAM upload
normal FW binary executable image with checksum
FX3 bootloader version: 0x000000A9
writing image...
transfer execution to Program Entry at 0x40014984
```

Following execution, the device will re-enumerate on the USB bus with its operational QHY vendor and product IDs.

---

## 4. Automated Udev Rule Configuration

To automate firmware upload whenever the camera is attached or powered on:

Create `/etc/udev/rules.d/99-qhyccd_custom.rules`:

```bash
sudo tee /etc/udev/rules.d/99-qhyccd_custom.rules <<'EOF'
ACTION!="add", GOTO="qhy_end_new"
SUBSYSTEM!="usb", GOTO="qhy_end_new"

# Trigger FX3 firmware upload upon detection of the WestBridge bootloader
ATTRS{idVendor}=="1618", ATTRS{idProduct}=="0485", ENV{LD_LIBRARY_PATH}="/usr/local/lib", RUN+="/usr/local/sbin/fxload -t fx3 -I /lib/firmware/qhy/QHY5III485.img -d 1618:0485"

# Grant standard user read/write access to QHY USB devices
ATTRS{idVendor}=="1618", MODE="0666"

LABEL="qhy_end_new"
EOF
```

> [!IMPORTANT]
> Replace `/lib/firmware/qhy/QHY5III485.img` with the exact firmware filename corresponding to your specific camera model.

Reload udev rules:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```