# UPDATE
Every since https://github.com/aaronwmorris/indi-allsky/pull/1488, the following indexes are no longer needed.


## LEGACY INFO
indi-allsky already makes extensive use of database indexes for peformance, but even those sometimes have limits.


The following indexes will turbo charge your image viewer experience!

### SQLite
```
sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite 'CREATE INDEX idx_image_createDate_YmdH on image (CAST(STRFTIME("%Y", "createDate") AS INTEGER), CAST(STRFTIME("%m", "createDate") AS INTEGER), CAST(STRFTIME("%d", "createDate") AS INTEGER), CAST(STRFTIME("%H", "createDate") AS INTEGER));'

sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite 'CREATE INDEX idx_video_dayDate_Ym on video (CAST(STRFTIME("%Y", "dayDate") AS INTEGER), CAST(STRFTIME("%m", "dayDate") AS INTEGER));'

sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite 'CREATE INDEX idx_mini_video_dayDate_Ym on mini_video (CAST(STRFTIME("%Y", "dayDate") AS INTEGER), CAST(STRFTIME("%m", "dayDate") AS INTEGER));'

```

### MariaDB
MariaDB does not appear to support functional indexes
