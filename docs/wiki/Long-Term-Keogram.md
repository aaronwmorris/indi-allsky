# Overview
indi-allsky has the ability to produce a long term keogram, sometimes referred to a "year long keogram".

The algorithm is agnostic to the length of the exposures and missing data is gracefully handled. 

## SyncAPI support
The long term keogram data is included with the SyncAPI so it is available on the remote instance.

## Generating
| Parameter | Usage |
| --------- | ----- |
| Start     | This is the starting point of the generated keogram |
| Timeframe | The time period for the generated keogram |
| Pixels Per Day | indi-allsky pulls 5 pixels per image for the keogram.  This is the number of pixels to use for each row.  More pixels means the day (row) will be taller |
| Alignment | This is the window used to align the timestamps of every sample.  The alignment window should be at least slightly larger than the period of your exposures.  For example, if you use a 30s exposure period, your alignment window should be 40s or greater.<br><br>Using a smaller alignment will result in gaps in your data.  Multiple samples that fall within the same alignment window will be averaged together.<br><br>A 60s alignment will result in 1440 generated samples per day with the image being 1440 pixels wide.<br><br>A 20s alignment will result in 4320 generated samples |
| Hour Offset | This can be used to shift the graph left or right.  The timestamps are UTC, but the date calculations are in the local timezone of the system.  If you use the SyncAPI, there can be an offset between these two.|

### MySQL/MariaDB
On my longer running all sky cameras which used MariaDB, I noticed the Long Term Keogram Generator would fail with an exception of a filesystem being out of space.  My investigation indicates either SQLAlchemy or MariaDB might be using temporary space in the `/tmp` filesystem and if there is not enough space available in `/tmp` the generator would fail.

```
raise get_mysql_exception(#012mysql.connector.errors.DatabaseError: 3 (HY000): Error writing file '/tmp/#sql/fd=104' (Errcode: 28 "No space left on device")
```