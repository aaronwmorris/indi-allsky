# Archive sync

Archive sync sends pending local media to another indi-allsky installation, even if it is only occasionally available. Use `Live sync` to send new captures as they become ready.

## Set up

1. Update both sender and receiver to a version supporting Archive sync.
2. In the sender's configuration, open `SyncAPI`, enable `Sync API` and choose `Archive sync`. Enter the receiver's URL, username and API key, or keep your existing working settings.
3. Select the content to transfer and an `Upload speed limit`. Lower limits leave more bandwidth for browsing and other network traffic; `Unlimited` is the default.
4. Click `Save Configuration` and allow the service to reload.

Images, panoramas, timelapses, mini timelapses, keograms, star trails and their videos are selected by default. RAW and FITS are optional. Associated thumbnails and camera/image metadata are included.

## Start a run

When the receiver is ready, click `Sync now`. It uses the current content selection and speed limit, including unsaved changes. Capture continues, and you can close the page. Cancel an active run before changing its speed.

Files transfer oldest first across the selected types. A run includes retained local-camera media older than ten minutes, even if it is more than thirty days old. Hidden cameras and unfinished media are excluded. Files completed during the run wait for the next run. `Live sync`'s image sampling, S3 delay and empty-file options do not apply.

Completed transfers are skipped on later runs. Before retrying an interrupted transfer, the sender checks whether the receiver already accepted the file. Missing local files are reported as skipped.

## Sync automatically when available

Enable `Automatically sync when available`, choose the timings, then click `Save Configuration`:

- `Check every`: how often to check the receiver; default 10 minutes.
- `Wait after availability`: extra startup time after the receiver responds; default 0 minutes (start immediately). Increase it if the receiver needs extra startup time.

Checks use your SyncAPI credentials to verify that the receiving application is ready. If it is unavailable, the sender quietly waits for the next check. If ready, it starts a run. With a startup delay set, it waits and checks again before starting. After completion or a lost connection, the cycle repeats. No checks are needed when nothing is pending.

The schedule uses saved content and speed settings and works with the browser closed. After a service restart, it begins a fresh check interval. Only one run is active at a time; a manual run temporarily suspends scheduled checks. Cancel an active run before changing its schedule.

## Stop or resume

- Cancelling a manual run leaves the schedule enabled if it was already enabled.
- Cancelling a scheduled run also pauses the schedule, including after a restart. Enable `Automatically sync when available` and click `Save Configuration` to resume it.
- With the schedule disabled, transfers wait until you click `Sync now`.

Temporary connection failures receive two retries. Account, certificate and other errors requiring attention stop the run and pause the schedule. Correct the displayed problem, then start manually or enable and save the schedule again. Cancellation may wait for a blocked network operation to time out.

## Progress and limits

The status panel shows completed items, uploaded files, transferred bytes, recent speed in MB/s, items/files per second and the next scheduled action. Recovered transfers can count as completed without uploading again. Large-file progress is provisional until the receiver confirms receipt.

An upload must finish within the receiver's roughly 20-minute authentication window. If the chosen speed limit is too low for a file, the run asks you to increase it.

Transfer history belongs to one receiver URL and account. Restore those settings if a destination-change warning appears; changing the API key is allowed.

Archive sync is not a full backup or mirror. It does not recheck previously completed files for later changes or deletion on the receiver. Deleting expired files on the sender does not delete their receiver copies. Configuration is not transferred; download it separately if needed.
