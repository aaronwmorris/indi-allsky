# When the live image stops updating

The exposure, processing of the image, and the browser's connection are independent. A camera connected directly to the capture host can keep recording through a Wi-Fi outage. An INDI camera on a remote host still needs a working network path to its driver.

For a Wi-Fi-only Pi that travels between networks, see [Wi-Fi recovery](Wi-Fi-Recovery.md). The optional helper uses NetworkManager independently of the capture service.

* If the Pi responds but the image is old, compare the last stored capture with the current time. Allow for exposure, the configured capture interval and processing. A scheduled pause or disabled daytime capture is expected.

Open **Status** at the bottom of the sidebar to see the capture state and image age together, for example **RUNNING · Last image 12 s ago**. On the live view, the age refers to the picture on screen and changes to the new frame’s age once that frame has loaded. On other pages it refers to the latest available image for the selected camera.

If the capture worker loses its INDI connection, it publishes **NO INDISERVER** before exiting for a retry. A camera removal is reported as **NO CAMERA**. These states appear in the same status field even if the last image is still recent. If the browser loses contact with the web server, the field shows the connection error until a fresh report arrives. The browser retries automatically, and **Retry now** checks again immediately.

On a source installation, `systemctl --user status indi-allsky.service gunicorn-indi-allsky.service` separates the capture service from the web application. In the default SQLite installation you can inspect the capture supervisor's status without modifying the database:

```sh
sqlite3 -readonly /var/lib/indi-allsky/indi-allsky.sqlite \
  "SELECT value FROM state WHERE key = 'CAPTURE_HEALTH';"
```

`raw_received` and `image_published` are Unix timestamps: the first means the driver supplied a nonempty file, the second that the image worker made a complete live image available. The `updated` timestamp tells you how recent the status itself is. The capture supervisor measures elapsed time independently of NTP corrections. A limited recovery of the capture service does not reboot the host or restart an independent UPS service.

* A failed local web interface can recover independently. See [Web service recovery](Web-service-recovery.md).
* If a configured sensor cannot provide a valid sample, its driver retries independently. New images store the validity of their sensor readings, so the sensor charts leave a gap for a failed reading and show a measured zero. The local status panel can show archive warnings and stale UPS readings to administrators. An optional local UPS monitor retries its I²C connection after repeated read failures.
* The archive monitor checks the configured image directory, its expected mount, free blocks and inodes, and an actual write. When space runs low, scheduled video and export jobs wait in the queue. When the archive is unavailable or full, capture pauses too. Checks continue and pending jobs resume in batches. The previously verified mount and entries in `/etc/fstab` protect a missing external disk. If you use a manually mounted volume, you can set `INDI_ALLSKY_ARCHIVE_MOUNT` to the expected mount point before starting the service for the first time.
* The video worker checks the last three completed nights within the configured image and timelapse retention periods. It decodes a frame before accepting a movie, records a failed repair against its source images, and retries when those sources change. Explicitly deleted videos stay deleted. Existing working videos remain available while replacements are encoded and verified.

Panorama videos use a browser-sized frame of up to 1920 × 1080 pixels. The archived panorama images keep their original resolution. If a panorama plays with a frozen picture, the video worker can rebuild it from the archived images in capture order. It counts the decoded frames before replacing the video at its existing watch URL. If too few source images remain to reproduce the full length of a readable video, the worker keeps the existing file.
