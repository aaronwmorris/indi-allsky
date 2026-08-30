# Design principles
I have tried to take security considerations as a first class design principle.  While there may be some compromises security-wise, I have tried to do the Right Thing© to minimize risks.

# General
* All software components run as a non-privileged (non-root) user.  Any user may be used--the pi user is not assumed.
    * indiserver
    * indi-allsky
    * flask
* The user used will be added as a member of the following groups for device access:
    * `video` - Access to web cameras
    * `dialout` - Access to serial ports
    * `gpio` - Access to GPIO pins
    * `i2c` - Access to I2C bus (sensors)
    * `spi` - Access to SPI bus (sensors)

# Privileged Access
The indi-allsky OS user is assigned the following designated privileged actions:
* Shutdown/reboot system (via web inteface)
* Set system time (via web interface)
* Auto-mount USB sticks

All of these activities are performed via standard [SystemD](https://www.freedesktop.org/wiki/Software/systemd/) and [udisks](https://www.freedesktop.org/wiki/Software/udisks/) interfaces.  Privileges are assigned using standard [polkit](http://www.freedesktop.org/wiki/Software/polkit) definitions.

# Passwords
* There is an option to encrypt passwords in the database using [Fernet](https://cryptography.io/en/latest/fernet/) symmetric encryption.  The encryption key is stored in `/etc/indi-allsky/flask.json` as `PASSWORD_KEY`

# Web Interface
The web interface is designed to run with a self-signed server certificate.  The certificate is generated on first run of setup.sh and is stored in with the system server certificates in `/usr/local/share/ca-certificates/` and added to the system trust store.
* 4096 bit key
* SHA512 hash
* SAN extension

[Flask](https://flask.palletsprojects.com/) is used as the application server layer.  CSRF tokens are used for all server interactions and should prevent most cross-site scripting attacks.
* [CSRF](https://en.wikipedia.org/wiki/Cross-site_request_forgery) tokens to prevent XSS attacks
* [HSTS](https://en.wikipedia.org/wiki/HTTP_Strict_Transport_Security) to enforce HTTPS mode
* Argon2 password hashing
* Session cookies are set with secure flag
* [SQLAlchemy](https://www.sqlalchemy.org/) ORM to prevent SQL injection attacks
* 3 levels of access control
    * Anonymous - only able to view images and videos
    * Staff - Able to view indi-allsky and system configuration, not able to make changes
    * Admin - Full administrative control
* Authentication is provided by [flask-login](https://flask-login.readthedocs.io/) and is controlled via IDs in the indi-allsky database.

# File transfers
indi-allsky supports several secure (and unsecure) file transfer protocols.  indi-allsky may bypass certificate and host key validations for convenience.

# SyncAPI
An internal REST-like interface is implemented to support synchronizing data between indi-allsky instances.  An API key is used to create an HMAC signature of the data and [the API key] is never directly transmitted over the network.

# Warnings
* indi-allsky uses various astronomy and image manipulation related python libraries.  Most of these libraries are community managed and may contain security vulnerabilities.