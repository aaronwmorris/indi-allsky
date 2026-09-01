# Overview
Backup and recovery of indi-allsky involves backing up several areas
1. Database
1. Database migrations
1. Flask config
1. indi-allsky environment (optional)
1. Images and videos

## Automated database backups
NOTE: indi-allsky now automatically schedules and creates database backups (SQLite only).  The default backup schedule is every 7 days and is configurable.  Backups are stored in `/var/lib/indi-allsky/backup/`.  Seven (7) database backups are retained and older backups are automatically deleted.

Database backups can be automatically uploaded to a remote FTP/SFTP server using the file transfer configuration.

## Database
### SQLite database
#### Manual Backup with Backup API
```
# Backup (backup API)
DB_BACKUP="backup_indi-allsky_sqlite_$(date +%Y%m%d_%H%M%S).sqlite"
sqlite3 "/var/lib/indi-allsky/indi-allsky.sqlite" ".backup $DB_BACKUP"
gzip "$DB_BACKUP"

# Restore (backup API)
gunzip -c backup_indi-allsky_sqlite_00000000.sqlite.gz > /var/lib/indi-allsky/indi-allsky.sqlite
```
*Note: You can backup the binary sqlite database file itself, but it is **NOT** portable between platforms (eg ARM -> Intel)*

#### Platform agnostic backups
```
# Backup (dump)
sqlite3 "/var/lib/indi-allsky/indi-allsky.sqlite" .dump | gzip -c > "backup_indi-allsky_sqlite_$(date +%Y%m%d_%H%M%S).sql.gz"

# Restore (dump)
gunzip -c backup_indi-allsky_sqlite_00000000.sql.gz | sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite
```

### Mysql database
```
# Backup
mysqldump --host localhost --user indi_allsky_own -p indi_allsky | gzip -c > "backup_indi-allsky_mysql_$(date +%Y%m%d_%H%M%S).sql.gz"

## add --ssl for remote connections

# Restore (create database first)
gunzip -c backup_indi-allsky_mysql_00000000.sql.gz | mysql --host localhost --user indi_allsky_own -p indi_allsky
```

* Mysql database creation:  https://github.com/aaronwmorris/indi-allsky/wiki/MySQL-MariaDB-Information

## Database migrations
```
# Backup
tar -C /var/lib/indi-allsky/migrations --exclude="*.py[oc]" -cvf - . | gzip -c > "backup_indi-allsky_migrations_$(date +%Y%m%d_%H%M%S).tgz"

# Restore
tar -C /var/lib/indi-allsky/migrations -xvfz backup_indi-allsky_migrations_00000000.tgz
```

## Flask config
The flask config is at `/etc/indi-allsky/flask.json`

## indi-allsky environment
Service environment variables are located at `/etc/indi-allsky/indi-allsky.env`.  This is an optional file.

## Images and videos
Images and videos are normally located at `/var/www/html/allsky/images/`

# Migrate to a newer OS
1. Install a new OS
1. Perform full indi-allsky setup as if setting up a new system
1. Disable indi-allsky auto-start on new system

        systemctl --user disable indi-allsky.timer

1. Once the web interface is online on the NEW system, delete the following files (on the NEW system)

        # do not forget the asterisk, could be up to 3 files
        rm -i /var/lib/indi-allsky/indi-allsky.sqlite*
        
        rm -i /var/lib/indi-allsky/migrations/versions/*.py

1. Copy the files in /etc/indi-allsky/ from the old system to the new system.

        rsync -pv /etc/indi-allsky/flask.json username@newallsky.local:/etc/indi-allsky/.
        
        # this file might not exist
        rsync -pv /etc/indi-allsky/indi-allsky.env username@newallsky.local:/etc/indi-allsky/.

1. Copy the database migrations from the old system

        rsync -pv /var/lib/indi-allsky/migrations/versions/*.py username@newallsky.local:/var/lib/indi-allsky/migrations/versions/.

1. Perform a backup of the SQLite database using the commands above.  Copy the export to the new system and restore using instructions above.
1. Restart the gunicorn service on the new system

        systemctl --user restart gunicorn-indi-allsky

1. You should be able to navigate to the web interface and see your original camera referenced.  If so, copy your original images to the new system.  This might take a while.

        rsync -prv /var/www/html/allsky/images/. username@newallsky.local:/var/www/html/allsky/images/.

1. Re-run `setup.sh` on the new system to fix any outstanding file permissions issues.
1. If all is well, you should be able to view images in the Gallery, Image Viewer, and Timelapse views.
1. Move your camera to the new system
    * Reboot your system if you hot-plugged your camera.
    * libcamera cameras may need overlays setup.  Make sure your camera is detected.
1. Try to start the capture process now and verify new images are generated

        source virtualenv/indi-allsky/bin/activate
        
        ./allsky.py run
        
        (Ctrl-C to stop)

1. Re-enable indi-allsky auto-start

        systemctl --user enable indi-allsky.timer

1. Start indi-allsky

        systemctl --user start indi-allsky

## Possible issues
* If INDI is a newer release, there is a small chance that your camera might get renamed which would result in a new camera entry.  There are ways to rename the camera entries in the database, please open a support issue.

* There is now a script `./misc/merge_cameras.py` to merge two camera entries into one and all of the images will be merged in the database.