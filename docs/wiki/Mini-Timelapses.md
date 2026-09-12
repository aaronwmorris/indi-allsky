# Overview

Mini-timelapses turn a selected period of saved images into a short video, for example to highlight a meteor, passing clouds, or an aurora. You can use the normal all-sky images, or crop saved panorama images and optionally pan between two views.

The video is generated from the saved images, so you do not need an existing full-day or full-night timelapse. An animated preview helps you choose the time range, playback speed, and framing before creating the video.

* [Create a mini-timelapse](#generate)
* [Check the preview and video size](#preview-speed-and-file-size)
* [Crop a panorama](#panorama-mini-timelapses)
* [Pan between two areas](#pan-between-two-areas)
* [Find, download, or delete a video](#viewing-and-managing-videos)
* [Troubleshooting](#troubleshooting)

## Accessing the Interface

Open **Media -> Images** and find an image containing the event you want to highlight. Click **Mini Timelapse** beneath the image to open the generator. Sign in if prompted.

The selected image is the reference point for the time range. You choose how much time to include before and after it.

## Generate

1. If **Images to use** is shown, choose **All-sky images** for a normal mini-timelapse. Choose **Panorama images** to use the [cropping and panning controls](#panorama-mini-timelapses).
2. Set **Before selected image** and **After selected image**. Each offers periods from 1 minute to 12 hours.
3. Choose **Speed**, the playback frame rate in frames per second (FPS).
4. Choose **Bitrate/File size**. The displayed guidance helps you balance detail and file size.
5. Check the animated preview and the estimated video length and size.
6. Enter a **Description** so you can identify the clip later.
7. Click **Create video**. Wait for the confirmation that the video has been queued, then use **Open Mini Timelapses** to find it.

Generation runs in the background and may take a few minutes, depending on the number and size of the images and other queued work. You can leave the generator after receiving the confirmation.

These selections apply to this video; they do not change the regular timelapse settings or the saved source images.

## Preview, Speed, and File Size

### Playback speed

**Speed** changes how quickly the saved images play back. It does not change the camera's capture rate or add intermediate images.

* Lower FPS gives a longer, slower video.
* Higher FPS gives a shorter, faster video. Options include 30 and 60 FPS.
* Very low rates are useful when you want each image to remain visible longer. At 0.25 FPS, each image is shown for four seconds.

Video length depends on the number of usable images, not just the selected time range. For example, 120 images produce a 12-second video at 10 FPS, or a 24-second video at 5 FPS.

### Bitrate and estimated size

**Bitrate/File size** controls the target amount of video data. Higher bitrates allow more detail but produce larger files; lower bitrates reduce file size and may lose fine detail. The initial selection comes from the applicable day or night timelapse settings.

The generator shows bitrate guidance based on the output resolution and FPS, along with an estimated file size. The size hints in the bitrate selector refer to a minute of **finished video**, not a minute of captured sky. These are estimates; the encoded file may differ.

### What the preview shows

The generator checks the full selected period for usable images and shows the available frame count, time range, and approximate video length. Wait for that check to finish before creating the video. Changing the source or time range reloads the preview.

**For periods longer than four hours, the animated preview shows only the last four hours. The finished video still uses the full selected period.** Panorama panning is also calculated over the full period, so a shortened preview may show only the later part of the movement.

Use the preview to check the content and framing. Browser image loading can affect playback, and the preview does not show the compression quality of the final encoded video. Click the preview to view it fullscreen where supported.

## Panorama Mini-Timelapses

The **Panorama images** option appears when **Enable Fisheye to Panoramic** is enabled. It uses panoramas that have already been saved; enabling the option does not create panoramas for older images.

The selected image must have its own saved panorama. If it does not, the generator displays **No panorama was saved for this image** and offers **Previous panorama** or **Next panorama** links when nearby panoramas are available. Choose one of these to use a different reference image.

### Keep the view still

1. Choose **Panorama images** under **Images to use**.
2. Leave **View movement** set to **Keep the view still**.
3. Choose an **Aspect ratio**, or use **Free size**. Presets include landscape 16:9, portrait 9:16, square 1:1, and other phone and video formats.
4. Drag inside the selection to move it. Drag its edges or corners to resize it. A fixed aspect ratio keeps the chosen shape while resizing.
5. Check the animated preview, then finish the shared settings and click **Create video**.

The same area is used throughout the clip. The panorama wraps horizontally: a selection crossing the left or right edge is joined into one continuous view in the video.

The selected width and height determine the output resolution. Choosing 16:9 sets the shape; it does not automatically produce a 1920 x 1080 video. Open **Manual position and size** if you need exact pixel values. **Reset area** restores the selection while respecting the chosen aspect ratio.

## Pan Between Two Areas

Panning moves the crop across the panorama during the video. Use it to start on one part of the sky and finish on another, or to make a full turn around the horizon.

1. Choose **Panorama images**, then set **View movement** to **Pan between two areas**.
2. Set the crop's aspect ratio and size.
3. Position the selection in **First frame** where the video should start.
4. Position the selection in **Last frame** where it should finish.
5. Choose a **Horizontal route** and check the movement in the animated preview.
6. Enter the description and click **Create video** when ready.

The two editors show the first and last usable panoramas from the full selected period. The selections start in the same position. Move them to set different endpoints; resizing either selection updates both because the crop size stays constant throughout the video. Panning does not zoom in or out.

The **Editing** badge identifies which endpoint the **Manual position and size** fields currently affect. Click or drag in the other editor to switch endpoints. Different vertical positions also move the view up or down during the clip.

| Horizontal route | Movement |
| --- | --- |
| **Shortest route** | Takes the shorter horizontal path between the selections, crossing the panorama edge if needed. |
| **Left to right** / **Right to left** | Reaches the ending selection in the chosen direction. |
| **Full turn left to right** / **Full turn right to left** | Adds a complete turn in the chosen direction before reaching the ending selection. |

To make one complete 360-degree turn, leave the starting and ending selections at the same position and choose a **Full turn** route. With the same endpoints and a route without a full turn, there is no horizontal movement.

## Viewing and Managing Videos

Open **Media -> Mini Timelapses**, or follow **Open Mini Timelapses** after submitting a video. Both all-sky and panorama clips appear here; panorama clips have a **Panorama** badge.

Select the date and day/night entry associated with the reference image. Click a video thumbnail to open the player, then use **Download Video** to save a copy.

If your account has permission, **Delete video** removes the local mini-timelapse and its thumbnail after confirmation. It leaves the source images and any uploaded copies in place. Deletion is blocked while generation or an associated upload is still active; wait for those tasks to finish before retrying.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| **Create video** is unavailable | Wait for the image check to finish and read any message above the preview. A blocking problem must be resolved before the video can be queued. |
| Not enough usable images | At least two usable images must still be stored locally. Excluded images, missing or empty files, and images available only through remote storage do not count. Choose another reference image or a longer period with saved images. |
| No panorama for the selected image | Use a nearby panorama link, choose another image with a saved panorama, or switch to **All-sky images**. |
| Panorama dimensions differ | All panoramas used in one clip must have the same dimensions. If panorama settings changed during the period, select a shorter range with matching images. |
| The panorama horizon looks incomplete or distorted | Check the source images and fisheye-to-panorama settings. A fisheye circle cut off by the image borders can produce an incomplete panorama; cropping or panning cannot recover the missing area. |
| The preview does not cover the whole period | For selections longer than four hours, this is expected. The video uses the full period. |

For general information about video encoding and regular timelapse settings, see [Timelapses](https://github.com/aaronwmorris/indi-allsky/wiki/Timelapses).
