# Overview
indi-allsky tracks the sync status of images and videos by a flag in the database.  It is possible to reset this flag to indicate no files are synced and then re-sync all of your timelapses.

## Reset sync status
* Start SQLite session

        sqlite3 -table -header /var/lib/indi-allsky/indi-allsky.sqlite

* Remove the sync status of timelapses, keograms, and star trails.

        UPDATE video SET sync_id = NULL;
        UPDATE minivideo SET sync_id = NULL;
        UPDATE keogram SET sync_id = NULL;
        UPDATE startrail SET sync_id = NULL;
        UPDATE startrailvideo SET sync_id = NULL;
        UPDATE panoramavideo SET sync_id = NULL;

* Image resync (optional)

        UPDATE image SET sync_id = NULL;
        UPDATE panoramaimage SET sync_id = NULL;

* Resync

        # exit sqlite
        ./misc/upload_sync.py sync
