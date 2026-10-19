# Media Thumbnails

`indi-allsky` generates and manages preview thumbnails for all primary media objects to maintain rapid load performance across the web gallery and archive viewers.

---

## Supported Media Types

Thumbnails are automatically generated upon creation of the following assets:
* **Still Images & Captures** (Daily, Nightly, and Reference Frames)
* **Timelapse Videos** (`.mp4`)
* **Mini-Timelapses**
* **Keograms** (Single-Night and Long-Term)
* **Star Trails Images & Videos**
* **Panorama Images & Videos**

---

## Storage Architecture

Thumbnails are stored directly in the database (`thumbnail` table via `IndiAllSkyDbThumbnailTable`) rather than as hundreds of thousands of independent small files on the storage filesystem. This design:
1. Prevents inode exhaustion on flash storage (eMMC and SD cards).
2. Accelerates database-driven gallery queries with pre-cached base64 or binary image payloads.
3. Simplifies automated retention and cleanup when parent image records expire.

---

## Rebuilding Thumbnails

If thumbnails are missing following a filesystem restoration or legacy database migration, execute the thumbnail generation utility:

### Debian Package Installations
```bash
sudo indi-allsky-ctl rebuild-thumbnails
```

### Manual / Developer Installations
```bash
source /var/lib/indi-allsky/virtualenv/bin/activate
python /usr/share/indi-allsky/misc/create_thumbnails.py
```

---

## SyncAPI Synchronization

When media assets are synchronized to a remote portal using the SyncAPI:
* Thumbnails are synchronized via the dedicated `/sync/v1/thumbnail` endpoint.
* If a remote portal database is rebuilt independently, execute `indi-allsky-ctl rebuild-thumbnails` on the remote server to repopulate missing preview records.