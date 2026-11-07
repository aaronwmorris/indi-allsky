# When the live image stops updating

The exposure, processing of the image, and the browser's connection are independent. A camera connected directly to the capture host can keep recording through a Wi-Fi outage. An INDI camera on a remote host still needs a working network path to its driver.

For a Wi-Fi-only Pi that travels between networks, see [Wi-Fi recovery](Wi-Fi-Recovery.md). The optional helper uses NetworkManager independently of the capture service.

* If the companion reports a lost connection, leave the window open. It retains the last decoded frame and checks again when the connection returns or the window becomes visible. A chart failure need not interrupt the live image.
* If the Pi responds but the image is old, compare the last stored capture with the current time. Allow for exposure, the configured capture interval and processing. A scheduled pause or disabled daytime capture is expected.
* If a new image is being loaded, the displayed timestamp still describes the visible image. It advances when the replacement is ready to display.

On a source installation, `systemctl --user status indi-allsky.service gunicorn-indi-allsky.service` separates the capture service from the web application. In the default SQLite installation you can inspect the capture supervisor's status without modifying the database:

```sh
sqlite3 -readonly /var/lib/indi-allsky/indi-allsky.sqlite \
  "SELECT value FROM state WHERE key = 'CAPTURE_HEALTH';"
```

`raw_received` and `image_published` are Unix timestamps: the first means the driver supplied a nonempty file, the second that the image worker made a complete live image available. The `updated` timestamp tells you how recent the status itself is. The capture supervisor measures elapsed time independently of NTP corrections. A limited recovery of the capture service does not reboot the host or restart an independent UPS service.
