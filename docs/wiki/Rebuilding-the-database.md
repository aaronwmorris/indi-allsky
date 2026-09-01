# General

## Integrity Check
If the database has become corrupted, try to run an integrity check.  A common error for a corrupted database is `sqlite3.DatabaseError: database disk image is malformed`

```
sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite "PRAGMA integrity_check;"
```

### Recover by dumping
Another alternative is to run a `.dump`
```
cd /var/lib/indi-allsky

sqlite3 indi-allsky.sqlite ".dump" > recover_indi-allsky.sql

# move the corrupted files out of the way
mkdir bad_db
mv indi-allsky.sqlite* bad_db

cat recover_indi-allsky.sql | sqlite3 indi-allsky.sqlite

sqlite3 indi-allsky.sqlite "PRAGMA integrity_check;"
```



## MySQL/MariaDB Integrity Check
```
sudo mysqlcheck -u root indi_allsky --analyze

sudo mysqlcheck -u root indi_allsky --repair
```


## Rebuild
If the sqlite database becomes corrupted or you move the files to a new device, you can easily rebuild the sqlite DB.

The import process will try to reimport all images, dark frames, timelapse videos, and keograms.
1. Enter the indi-allsky git checkout folder

        cd indi-allsky

1. Activate virtualenv

        source virtualenv/indi-allsky/bin/activate

1. Stop services

        systemctl --user stop indi-allsky
        systemctl --user stop gunicorn-indi-allsky.socket
        systemctl --user stop gunicorn-indi-allsky.service

1. Delete the old sqlite DB

        rm -f /var/lib/indi-allsky/indi-allsky.sqlite
        rm -f /var/lib/indi-allsky/indi-allsky.sqlite-shm
        rm -f /var/lib/indi-allsky/indi-allsky.sqlite-wal

1. Remove the previous alembic migrations

        rm -f /var/lib/indi-allsky/migrations/versions/*.py

1. Recreate the DB with alembic

        flask db revision --autogenerate
        flask db upgrade head

1. Bootstrap the config in the DB

        ./config.py bootstrap

1. Find the camera driver name
This needs to be the driver name returned by INDI.  You may see multiple drivers listed here, pick the name of the camera.
_If you are using a libcamera type camera, the name should be something like `libcamera_imx477`_
    * Do not worry if you use the incorrect name.  You will just end up with two cameras in the web interface.  You can just restart this process again and use the correct name on the second run.

             indi_getprop | grep DRIVER_NAME | awk -F= '{print $2}'

1. Import images and videos

        ./allsky.py dbImportImages

1. Recreate thumbnails

        ./misc/create_thumbnails.py

1. Import dark frames

        ./misc/import_darks_frames.py

1. Restart web services

        systemctl --user start gunicorn-indi-allsky.socket

1. If you need to create users, use this wiki guide:  https://github.com/aaronwmorris/indi-allsky/wiki/Web-Interface-Password

## Extracting an old configuration from a backup
If you need to pull a config file from an old backup, you can use the following steps.

1. Find the backup you want to restore in `/var/lib/indi-allsky/backup/`
1. Restore the database to a temporary file

        gunzip -c backup_00000000_0000000.sql.gz | sqlite3 /tmp/restore_indi-allsky.sqlite

1. Identify a version (by id) you wish to extract

        sqlite3 /tmp/restore_indi-allsky.sqlite -header -table "SELECT id,level,note FROM config ORDER BY createDate DESC;"

1. Extract the config (replace ##### with id number)

        sqlite3 /tmp/restore_indi-allsky.sqlite "SELECT data FROM config WHERE id=#####;" | json_pp > /tmp/extracted_config.json
        cat /tmp/extracted_config.json

1. The config is available at `/tmp/extracted_config.json`


## Restoring an extracted config into the current indi-allsky database
You may even restore a config into your current database.  WARNING: This will overwrite all of your existing settings.  The current config is still in the database and you have the option to revert the config.

* Restore a config

        source virtualenv/indi-allsky/bin/activate
        
        ./config.py load --config /tmp/extracted_config.json --force


### Revert a configuration
If you want to revert to an older configuration in the existing database, follow these steps

1. Identify the config version you wish to restore

        source virtualenv/indi-allsky/bin/activate
        
        ./config.py list

1. Revert the config (replace ##### with the id)

        ./config.py --id ##### revert