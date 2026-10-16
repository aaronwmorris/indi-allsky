# General
Reducing disk I/O on SD and MMC class storage devices can significantly extend their lifetime.

You can monitor per-process disk IO with `sudo iotop -oPa`

## journald
systemd journald logging contributes to a significant amount of disk I/O.  Changing the storage to `volatile` only logs to memory.  This can result in an **80% reduction** of IOs on a standard all sky system.

![Screenshot_20230219_205900](https://user-images.githubusercontent.com/17464290/219992113-0440463a-e339-4938-b62b-0f29f8da0076.png)

```bash
sudo mkdir /etc/systemd/journald.conf.d

sudo tee /etc/systemd/journald.conf.d/90-indi-allsky.conf <<EOF
[Journal]
Storage=volatile
Compress=yes
RateLimitIntervalSec=30s
RateLimitBurst=10000
SystemMaxUse=20M
EOF

sudo systemctl restart systemd-journald 
```

## ext4 commit interval
Add `commit=300` to the mount options for the filesystems.
* File: `/etc/fstab`

        UUID=abcdabcd-1234-4c97-1234-181c2d402646   /   ext4    defaults,noatime,commit=300 0   1


## Decrease swappiness
This will decrease the rate at which the Linux kernel will swap out memory pages to the swap file and reduce disk I/O.
```bash
echo "vm.swappiness = 1" | sudo tee /etc/sysctl.d/90-indi-allsky.conf

sudo sysctl --system
```

## tmpfs
Utilize a memory backed filesystem for /tmp to reduce writes

```
# /etc/fstab
...
tmpfs /tmp tmpfs defaults,nosuid,size=512m 0 0
...
```

## Relocating the Image Directory to External Storage

To eliminate image capture writes to the SD card, you can move the image directory to an attached SSD, hard drive, or USB flash drive:

1. **Stop services:**
   ```bash
   sudo systemctl stop indi-allsky.service gunicorn-indi-allsky.service
   ```

2. **Create target directory & copy existing images:**
   ```bash
   sudo mkdir -p /mnt/storage/allsky/images
   sudo rsync -av /var/www/html/allsky/images/ /mnt/storage/allsky/images/
   ```

3. **Update Flask configuration (`/etc/indi-allsky/flask.json`):**
   Set `INDI_ALLSKY_IMAGE_FOLDER` to your new path:
   ```json
   "INDI_ALLSKY_IMAGE_FOLDER": "/mnt/storage/allsky/images",
   ```

4. **Update Camera configuration:**
   In the Web UI under **Configuration &rarr; Camera Settings**, set **`IMAGE_FOLDER`** to `/mnt/storage/allsky/images` (or via CLI with `indi-allsky-ctl config`).

5. **Repair and apply directory permissions with `indi-allsky-ctl`:**
   ```bash
   sudo indi-allsky-ctl fix-perms
   ```
   *`fix-perms` inspects `/etc/indi-allsky/flask.json` and the database, automatically creating `darks/` and `export/` subdirectories and applying `chown -R indi-allsky:www-data` and `chmod 775` permissions.*

6. **Restart services:**
   ```bash
   sudo systemctl start indi-allsky.service gunicorn-indi-allsky.service
   ```