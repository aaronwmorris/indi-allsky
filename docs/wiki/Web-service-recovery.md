# Web service recovery

Gunicorn restarts after process failure, with up to three starts per 15 minutes. For source installations using systemd user services, an optional timer also checks the response of an already running Gunicorn instance and the local HTTPS reverse proxy once a minute. Both probes request `/indi-allsky/healthz`, a small Flask response that works independently of the camera, database and login service.

From the source checkout, run these commands as the camera user after updating the application:

```sh
bash misc/setup_web_recovery.sh install
systemctl --user status indi-allsky-web-recovery.timer
journalctl --user -u indi-allsky-web-recovery.service --since today
```

The default Gunicorn unit is `gunicorn-indi-allsky` and the proxy is checked on loopback HTTPS port 443. If your installation uses another unit or port, pass both after `install`, for example `install gunicorn-secondary 8443`. When updating an already running web service, reload its workers to expose the new endpoint. The timer also installs the restart policy as a drop-in for existing user units.

The helper derives the Unix socket path from the active socket unit. Three consecutive failed backend checks can request a restart of that same Gunicorn instance. There is a 15-minute cooldown and a limit of two such restarts per hour. A successful direct probe and failed proxy probe appears in the journal as a proxy problem. An unexpected HTTP route or login page is recorded as a mismatch. An inactive service or socket is skipped, so the timer does not wake a deliberately stopped web service.

For maintenance, stop the socket and service together to prevent ordinary browser requests from activating Gunicorn. With default unit names:

```sh
systemctl --user stop gunicorn-indi-allsky.socket gunicorn-indi-allsky.service
systemctl --user start gunicorn-indi-allsky.socket
```

The installer only manages the observer and its service drop-in. Remove them with `bash misc/setup_web_recovery.sh remove` (use the same unit basename if customized).
