# Overview
When you setup a new camera with indi-allsky, the old camera entry will remain active in the Camera dropdown.  The following SQL may be used to hide an old camera entry.  The data will remain in the database, but inactive.

Note:  If you start indi-allsky using a camera from a hidden entry, the camera will be automatically un-hidden.

## Setup
Start a sqlite session with the following command
```bash
sqlite3 -table -header /var/lib/indi-allsky/indi-allsky.sqlite
```

## Hide cameras
Use this to hide cameras from web interface.
```
sqlite> SELECT id, name, friendlyName, hidden FROM camera;
+----+------------------+--------------+--------+
| id |       name       | friendlyName | hidden |
+----+------------------+--------------+--------+
| 1  | CCD Simulator    |              | 0      |
| 2  | ZWO CCD ASI290MM |              | 0      |
+----+------------------+--------------+--------+

sqlite> UPDATE camera SET hidden=1 WHERE id=1;
```

## Merge Cameras
Sometimes the camera name will change if you upgrade the indilib library.  This will result in 2 camera entries in the camera dropdown.

indi-allsky includes a script that will merge the old camera data with the new camera leaving a single entry.

```
./misc/merge_cameras.py
```