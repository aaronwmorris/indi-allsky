# Security Architecture & Hardening

`indi-allsky` incorporates defense-in-depth principles across process isolation, credential cryptography, network restrictions, and web application security.

---

## 1. Process Isolation & Least Privilege

* **Unprivileged Execution**: All background services (`indi-allsky.service`, `gunicorn-indi-allsky.service`, `indiserver.service`) execute under a dedicated non-root service account (`indi-allsky`).
* **Group-Based Hardware Access**: Hardware access is delegated via standard Linux supplementary groups:
  * `video`: Camera access (V4L2, libcamera).
  * `dialout`: Serial interfaces (GPS, RS-232 focusers, udev devices).
  * `gpio`: Access to `/dev/gpiochip*` for dew heaters, fans, and focusers.
  * `i2c`: Sensor buses (BME280, TSL2591, MLX90614, etc.).
  * `spi`: SPI-driven display modules and sensors.
* **Controlled Privileged Operations**: System-level commands (rebooting, power management, time synchronization, and USB drive auto-mounting) are mediated via PolicyKit (`/etc/polkit-1/rules.d/90-indi-allsky.rules`) rather than `sudo` or SUID binaries.

---

## 2. Cryptography & Credential Security

* **Password Storage**: User passwords are encrypted with the **Argon2** password-hashing function via `passlib`, resisting GPU/ASIC brute-force attempts.
* **Configuration Secrets Encryption**: Sensitive configuration attributes stored in the database (API tokens, MQTT credentials, S3 secret keys, Wi-Fi passwords) are encrypted symmetrically using **Fernet** (AES-128-CBC with HMAC-SHA256).
  * The encryption key is stored on the filesystem in `/etc/indi-allsky/flask.json` (`PASSWORD_KEY`).
  * If `PASSWORD_KEY` is lost or altered, stored third-party credentials must be re-entered.
* **SyncAPI HMAC Signatures**: Synchronization between on-premises cameras and remote web portals utilizes pre-shared HMAC keys. Raw API keys are never transmitted over the network; each request payload is cryptographically signed and timestamped.

---

## 3. Web Application Security

The web layer (Flask, Flask-WTF, Flask-Login) includes standard defensive measures:
* **CSRF Protection**: All state-modifying POST/PUT operations require cryptographically signed CSRF tokens (`WTF_CSRF_TIME_LIMIT`).
* **SQL Injection Prevention**: Database interactions operate exclusively through SQLAlchemy ORM parameter binding; raw SQL concatenation is avoided.
* **Session Security**: Session cookies enforce `HttpOnly`, `SameSite=Lax`, and `Secure` attributes by default.
* **Role-Based Access Control**:
  * **Anonymous**: Restricted to viewing live images, charts, and public archives (or fully blocked if `INDI_ALLSKY_AUTH_ALL_VIEWS` is enabled).
  * **Standard User**: Authenticated access to media archives and astronomical status panels.
  * **Administrator**: Exclusive authority to modify hardware configurations, trigger calibration routines, manage users, and issue system control tasks.

---

## 4. Network Boundary & Remote Access Hardening

### Admin Network Restrictions (`ADMIN_NETWORKS`)
Administrative actions and Action API endpoints (`/indi-allsky/action/*`) require the requesting client IP address to reside within CIDR subnets defined in `/etc/indi-allsky/flask.json`:
```json
"ADMIN_NETWORKS": [
    "127.0.0.1/32",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16"
]
```

### Exposing to the Internet
If the allsky camera must be accessible outside the local area network:
1. **Prefer Encrypted Overlays**: Utilize Cloudflare Tunnels, Tailscale, or WireGuard rather than direct router port-forwarding.
2. **Require Authentication**: Set `"INDI_ALLSKY_AUTH_ALL_VIEWS": true` in `/etc/indi-allsky/flask.json` to prevent unauthenticated access to the live camera canvas.
3. **Protect Media Directories**: Set `"INDI_ALLSKY_AUTH_MEDIA_VIEWS": true` if image and timelapse archives should not be publicly indexable.