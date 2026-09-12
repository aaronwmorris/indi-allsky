# Overview

Mini-timelapses turn saved images into a short video highlighting an event, such as a meteor or aurora. Use normal all-sky images, or crop and pan across saved panoramas.

An animated preview helps you choose the time range, speed, and framing. You do not need an existing full-day or full-night timelapse.

* [Create a mini-timelapse](#generate)
* [Check the preview and video size](#preview-speed-and-file-size)
* [Crop a panorama](#panorama-mini-timelapses)
* [Pan between two areas](#pan-between-two-areas)
* [Find, download, or delete a video](#viewing-and-managing-videos)
* [Troubleshooting](#troubleshooting)

## Accessing the Interface

Find an image containing the event through either view:

* **Media -> Images:** click **Mini Timelapse** beneath the image.
* **Media -> Gallery:** open an image, then click the **Mini-Timelapse** button in the image viewer's toolbar.

Sign in if prompted. The selected image is the reference point for the time before and after the event.

## Generate

1. If **Images to use** is shown, choose **All-sky images** or **Panorama images** for [cropping and panning](#panorama-mini-timelapses).
2. Set **Before selected image** and **After selected image**. Each offers periods from 1 minute to 12 hours.
3. Choose **Speed**, the playback frame rate in frames per second (FPS).
4. Choose **Bitrate/File size** to balance detail and file size.
5. Check the animated preview and the estimated video length and size.
6. Enter a **Description** to identify the clip later.
7. Click **Create video**. After the queue confirmation, use **Open Mini Timelapses** to find it.

Generation runs in the background and may take a few minutes. You can leave the generator after receiving the confirmation.

These settings apply only to this video and leave the saved source images unchanged.

## Preview, Speed, and File Size

### Playback speed

**Speed** controls playback without changing the camera's capture rate or adding intermediate images.

* Lower FPS gives a longer, slower video.
* Higher FPS gives a shorter, faster video.
* At 0.25 FPS, each image remains visible for four seconds.

Video length depends on the usable image count: 120 images produce 12 seconds at 10 FPS, or 24 seconds at 5 FPS.

### Bitrate and estimated size

Higher **Bitrate/File size** settings allow more detail but produce larger files. The initial selection comes from the applicable day or night timelapse settings.

The generator provides bitrate guidance based on resolution and FPS, plus an estimated file size. The selector's size hints refer to a minute of **finished video**, not captured sky. The encoded file may differ from the estimate.

### What the preview shows

The generator checks the full selected period and shows the usable frame count, time range, and approximate video length. Changing the source or time range reloads the preview.

**For periods longer than four hours, the animated preview shows only the last four hours. The finished video uses the full selected period.** Panorama panning is calculated over the full period, so a shortened preview may show only the later part of the movement.

The preview shows content and framing, not final compression quality; browser image loading can affect playback. Click it for fullscreen where supported.

## Panorama Mini-Timelapses

**Panorama images** appears when **Enable Fisheye to Panoramic** is enabled. It uses panoramas already saved for the selected period.

The selected image must have its own saved panorama. Otherwise, **No panorama was saved for this image** appears with **Previous panorama** or **Next panorama** links when alternatives are available.

### Keep the view still

1. Choose **Panorama images** under **Images to use**.
2. Leave **View movement** set to **Keep the view still**.
3. Choose an **Aspect ratio**, or use **Free size**. Presets include landscape 16:9, portrait 9:16, square 1:1, and other phone and video formats.
4. Drag inside the selection to move it, or its edges and corners to resize it. A fixed aspect ratio preserves the shape.
5. Check the animated preview, then finish the shared settings and click **Create video**.

The same area is used throughout the clip. Selections crossing the panorama's left or right edge wrap into one continuous view.

The selected width and height determine the output resolution. Choosing 16:9 sets the shape; it does not automatically produce a 1920 x 1080 video. Open **Manual position and size** if you need exact pixel values. **Reset area** restores the selection while respecting the chosen aspect ratio.

## Pan Between Two Areas

Panning moves the crop between two areas of sky, or makes a full turn around the horizon.

1. Choose **Panorama images**, then set **View movement** to **Pan between two areas**.
2. Set the crop's aspect ratio and size.
3. Position the selection in **First frame** where the video should start.
4. Position the selection in **Last frame** where it should finish.
5. Choose a **Horizontal route** and check the movement in the animated preview.
6. Enter the description and click **Create video** when ready.

The editors show the first and last usable panoramas from the full period. Move their initially aligned selections to set different endpoints. Resizing either updates both: the crop size stays constant, without zooming.

The **Editing** badge shows which endpoint the **Manual position and size** fields affect. Click or drag in the other editor to switch. Different vertical positions also move the view up or down.

| Horizontal route | Movement |
| --- | --- |
| **Shortest route** | Takes the shorter horizontal path between the selections, crossing the panorama edge if needed. |
| **Left to right** / **Right to left** | Reaches the ending selection in the chosen direction. |
| **Full turn left to right** / **Full turn right to left** | Adds a complete turn in the chosen direction before reaching the ending selection. |

For one 360-degree turn, leave both selections at the same position and choose a **Full turn** route. Other routes produce no horizontal movement when the endpoints match.

## Viewing and Managing Videos

Open **Media -> Mini Timelapses**, or follow **Open Mini Timelapses** after submitting a video. Both all-sky and panorama clips appear here; panorama clips have a **Panorama** badge.

Select the date and day/night entry associated with the reference image. Click a video thumbnail to open the player, then use **Download Video** to save a copy.

If your account has permission, **Delete video** removes the local video and thumbnail after confirmation, leaving source images and uploaded copies in place. Wait for generation and associated uploads to finish before deleting.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| **Create video** is unavailable | Wait for the image check to finish and read any message above the preview. A blocking problem must be resolved before the video can be queued. |
| Not enough usable images | At least two usable images must still be stored locally. Excluded images, missing or empty files, and images available only through remote storage do not count. Choose another reference image or a longer period with saved images. |
| Panorama dimensions differ | All panoramas used in one clip must have the same dimensions. If panorama settings changed during the period, select a shorter range with matching images. |
| The panorama horizon looks incomplete or distorted | Check the source images and fisheye-to-panorama settings. A fisheye circle cut off by the image borders can produce an incomplete panorama; cropping or panning cannot recover the missing area. |

For general information about video encoding and regular timelapse settings, see [Timelapses](https://github.com/aaronwmorris/indi-allsky/wiki/Timelapses).
