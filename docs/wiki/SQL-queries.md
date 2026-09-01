# General
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

## Use Non-Local Images S3 with SyncAPI
If you are uploading images to S3, you can configure the web interface to serve images from S3 on the **REMOTE** SyncAPI server.  (This is not necessary on the local server)
```
sqlite> SELECT id, name, friendlyName, web_nonlocal_images, web_local_images_admin FROM camera;
+----+------------------+--------------+---------------------+------------------------+
| id |       name       | friendlyName | web_nonlocal_images | web_local_images_admin |
+----+------------------+--------------+---------------------+------------------------+
| 1  | CCD Simulator    |              | 0                   | 0                      |
| 2  | ZWO CCD ASI290MM |              | 0                   | 0                      |
+----+------------------+--------------+---------------------+------------------------+

sqlite> UPDATE camera SET web_nonlocal_images=1 WHERE id=1;
```

### (Optional) Admin local images
If you want to serve local images on admin networks (but serve S3 from non-admin networks) when uploading to S3
```
sqlite> UPDATE camera SET web_nonlocal_images=1 WHERE id=1;
sqlite> UPDATE camera SET web_local_images_admin=1 WHERE id=1;
```

## Queries
### Example of chart data
   * Averaging stars by 5 entries
   * Showing SQM deltas from previous entry
```sql
SELECT
    i.exposure,
    i.temp,
    i.adu,
    i.sqm,
    i.stars,
    i.detections,
    i.sqm,
    avg(i.stars) OVER (ORDER BY i.createDate ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) AS stars_rolling,
    i.sqm - lag(i.sqm) OVER (ORDER BY i.createDate) AS sqm_diff
FROM image i
JOIN camera c
    ON c.id = i.camera_id
WHERE
    c.id = 1 AND
    i.createDate > datetime(datetime('now'), '-15 MINUTE')
ORDER BY
    i.createDate DESC;
```

### Show number of seconds between each image and the last image for the last 24 hours.

```sql
SELECT
  i.id,
  i.createDate,
  ROUND(i.exposure, 2),
  ROUND(i.exp_elapsed, 2),
  ROUND(i.process_elapsed, 2),
  strftime('%s', i.createDate) - LAG(strftime('%s', i.createDate))
    OVER (ORDER BY i.createDate) AS date_diff
FROM image i
JOIN camera c
  ON i.camera_id = c.id
WHERE
  c.id = 1 AND
  i.createDate > datetime(datetime('now'), '-24 HOUR')
ORDER BY
  i.createDate DESC;
```

### Show SQM values and relative increase from last SQM value for the last hour.

```sql
SELECT
  i.id,
  i.createDate,
  CAST(i.sqm AS int),
  CAST((i.sqm - LAG(i.sqm) OVER (ORDER BY i.createDate)) AS int)
FROM image i
JOIN camera c
  ON i.camera_id = c.id
WHERE
  c.id = 1 AND
  i.createDate > datetime(datetime('now'), '-1 HOUR')
ORDER BY
  i.createDate DESC;
```