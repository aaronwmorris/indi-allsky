# Overview
indi-allsky supports several methods of file transfers.  All are implemented using native python features and modules.

| Protocol       | Class Name          | Port | Description |
| -------------- | ------------------- | ---- | ----------- |
| ftp            | pycurl_ftp          | 21   | FTP via pycurl |
|                | python_ftp          | 21   | FTP via ftplib |
| ftpes          | pycurl_ftpes        | 21   | FTPS (explicit) via pycurl |
|                | python_ftpes        | 21   | FTPS (explicit) via ftplib |
| ftps           | pycurl_ftps         | 990  | FTPS (implicit) via pycurl |
| sftp           | pycurl_sftp         | 22   | SFTP via pycurl |
|                | paramiko_sftp       | 22   | SFTP via paramiko |
| webdav (https) | pycurl_webdav_https | 443  | HTTPS PUT via pycurl |

# PycURL Options
  * You may add additional libcurl configuration options via the `PycURL Options` entry
  * Options may be added with `CURLOPT_` prefix or without
  * Examples
      * https://curl.se/libcurl/c/CURLOPT_VERBOSE.html
      * https://curl.se/libcurl/c/CURLOPT_SSH_PRIVATE_KEYFILE.html
      * https://curl.se/libcurl/c/CURLOPT_SSH_AUTH_TYPES.html


# File transfer variables
| Name           | Type         | Info |
| -------------- | ------------ | ---- |
| timestamp      | datetime     | https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes |
| ts             | datetime     | Shortcut for `timestamp` |
| day_date       | date         | Day reference for exposure.  Referencing the date when the timelapse set starts. |
| ext            | str          | File extension (no dot) |
| camera_uuid    | str          | Camera UUID |
| camera_id      | int          | Camera ID |
| timeofday      | str          | `night` or `day` |
| tod            | str          | Shortcut for `timeofday` |


# Atomic file transfers
Atomic file transfers upload the file as a temporary name then renames the file after it is fully uploaded.  This prevents images from being partially loaded when viewed while the file is being uploaded.

## Atomic support
* `pycurl_sftp`
* `pycurl_ftp`
* `pycurl_ftpes`
* `pycurl_ftps`


# SFTP
## PycURL SFTP
SFTP protocol implemented via libcurl.

* Does *not* support relative remote paths.  You may use tilde `~` for the remote home directory.
    * `~` shortcut is not compatible with atomic transfers
* You may have to manually accept the remote hostkey using ssh on the command line before file transfers can occur.
* Use Private and Public key inputs or `PycURL Options` for key based authentication
    * Both private and public keys must be specified
    * If you specify the public and private keys, the password field is used for the key password
    * Only supports rsa keys in PEM format when libcurl compiled with libgcrypt (Debian, Raspbian, etc)
        * Does **not** support dsa, ecdsa, or ed25519 keys
    * Convert keys using `ssh-keygen -p -m PEM -f /home/pi/.ssh/id_rsa`
        * Correct key:  `-----BEGIN RSA PRIVATE KEY-----`
        * If ssh key starts with `-----BEGIN OPENSSH PRIVATE KEY-----` **IT WILL NOT WORK**
* On Windows based SFTP servers, remote folder should NOT start with `/`.  Folder should be the drive<br>path: `C:/Users/foo bar/upload`


## Paramiko SFTP
SFTP protocol implemented via the paramiko module.

* Use Private Key input for key based authentication (public key is not used)
* Supports relative and full remote paths.
    * Does **not** support tilde `~` shortcut
* Automatically detects and uses ssh keys (rsa, dsa, ecdsa, ed25519) if located at default paths
    * https://docs.paramiko.org/en/stable/api/client.html#paramiko.client.SSHClient.connect
        * `$HOME/.ssh/id_rsa`
        * `$HOME/.ssh/id_dsa`
        * `$HOME/.ssh/id_ecdsa`
        * `$HOME/.ssh/id_ed25519`
* Host key validation is disabled by default
* On Windows based SFTP servers, remote folder should NOT start with `/`.  Folder should be the drive<br>path: `C:/Users/foo bar/upload`

# FTP
## PycURL FTP
FTP protocol implemented via libcurl.

## Python FTP
FTP protocol using Python's native ftp support.

## PycURL FTPES
FTPES protocol via libcurl.

* ftpes sessions start like a regular FTP session on port 21, but negotiate TLS encryption for authentication and data transfers.  Similar to START_TLS with SMTP or LDAP.
* Certificate validation is disabled by default

## Python FTPES
FTPES protocol via Python's native ftp support.

* ftpes sessions start like a regular FTP session on port 21, but negotiate TLS encryption for authentication and data transfers.  Similar to START_TLS with SMTP or LDAP.
* Certificate validation is disabled by default

## PycURL FTPS
FTPS protocol via libcurl.

* FTPS is implicitly encrypted for the full session.
* Certificate validation is disabled by default

# HTTP
## PycURL WebDAV
HTTP(S) protocol via libcurl.

* Remote server must support webdav/web disk.
* Encrypted when endpoint is `https://`
* Certificate validation is disabled by default

# Latest Images and Videos
The options related to latest images and videos allows you to upload the last generated image and videos to the remote server as a static filename so that this will always reference the latest version of the asset.

* latest_image.jpg
* latest_panorama.jpg
* latest_raw_image.jpg
* latest_timelapse.mp4
* latest_keogram.jpg
* latest_startrail.jpg
* latest_startrail_timelapse.mp4
* latest_panorama_timelapse.mp4

# Notes

* libcurl error codes:  https://curl.se/libcurl/c/libcurl-errors.html