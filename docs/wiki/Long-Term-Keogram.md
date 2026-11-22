# Long-Term Keograms

While standard keograms summarize a single night horizontally, **Long-Term Keograms** (frequently termed "annual keograms") compile dozens or hundreds of successive nights into a stacked two-dimensional composite:
* **Horizontal Axis (X)**: Time of night (e.g., dusk to dawn).
* **Vertical Axis (Y)**: Calendar dates progressing chronologically from top to bottom.

This format provides an astronomical climatology chart, visualizing seasonal changes in night length, recurring cloud patterns, moon phases, auroral activity, and seasonal smoke or haze over periods up to a full year.

---

## 1. Generation Parameters

Long-Term Keograms are generated via the web dashboard under **Archives** → **Long-Term Keograms**:

| Parameter | Recommended Setting | Description |
|---|---|---|
| **Start Date** | Target start date | The initial calendar date (`YYYY-MM-DD`) for the aggregate timeline. |
| **Timeframe** | `1 Month`, `3 Months`, `1 Year` | Total duration spanned along the vertical axis. |
| **Pixels Per Day** | `3` to `5` | Height (in pixels) allocated to each calendar night. Higher values produce larger images. |
| **Alignment Window** | `45s` to `60s` | Temporal sampling bucket. Must slightly exceed your night exposure cycle (e.g. if exposures are 30s, set window $\ge 40$s). Multiple frames within the window are averaged. |
| **Hour Offset** | Local UTC offset | Shifts the horizontal axis so local midnight aligns with the image center. |

---

## 2. SyncAPI Support

Long-term keogram records and image assets are tracked in `IndiAllSkyDbLongTermKeogramTable` and synchronize to remote web portal instances automatically via the SyncAPI endpoint `/sync/v1/keogram`.

---

## 3. Database Performance & Storage Considerations

Compiling a multi-month or annual keogram queries hundreds of thousands of frame records. Depending on the database engine, substantial intermediate sorting occurs:

### MariaDB / MySQL Disk Space in `/tmp`
When sorting large query result sets, MariaDB may generate temporary files in `/tmp`. On systems where `/tmp` is mounted as a small RAM-based `tmpfs` (e.g., on Armbian or Raspberry Pi OS), the query may fail with:
```text
mysql.connector.errors.DatabaseError: 3 (HY000): Error writing file '/tmp/#sql...' (Errcode: 28 "No space left on device")
```

**Resolution**:
Direct MariaDB temporary storage to a physical disk volume with sufficient capacity by editing `/etc/mysql/mariadb.conf.d/50-server.cnf` (or `/etc/mysql/my.cnf`):
```ini
[mysqld]
tmpdir = /var/tmp
```
Restart the service:
```bash
sudo systemctl restart mariadb
```