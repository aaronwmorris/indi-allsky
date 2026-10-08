# Dark calibration frames

**On this page:** [General information](#general-information) · [Web interface](#using-the-web-interface) · [Command line](#using-darkspy)

<a id="general"></a>

## General information

Dark frames record the sensor's noise with all light blocked. indi-allsky automates their capture and processing, combining several source images into a **master dark** and a **bad pixel map** to help correct noise and hot pixels. Together, these form a **master set**.

You can build a library through the web interface or use the original `darks.py` command-line tool. Both support average stacking and sigma clipping, which removes outliers before averaging.

> **Before capturing darks:** Cover the lens with something thick enough to block **all light**. Uncover the camera when the run ends.

### RAW mode

Use RAW, unprocessed camera output whenever possible. JPEG, PNG and other RGB sources are less suitable for dark calibration, but **both tools support them**, including cameras such as IP webcams that cannot provide RAW data.

| Source | Stacking method |
| --- | --- |
| RAW | Sigma clipping or average |
| JPEG, PNG or other RGB data | Average only |

#### Altair & Touptek

These drivers start color cameras in INDI_RGB mode by default. Change the camera configuration to INDI_RAW mode.

[Configure Altair & Touptek RAW mode](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config#touptek--altair-raw-mode)

#### Canon DSLR

Canon cameras normally start in JPEG mode. Set them to RAW mode for dark calibration.

[Configure Canon resolution and RAW mode](https://github.com/aaronwmorris/indi-allsky/wiki/INDI-custom-config#canon-resolution-and-raw-mode)

### Temperature and cooling

For controlled cooling, a 3–6 foot USB cable lets you place the camera in a refrigerator or freezer while keeping the computer at room temperature. If the camera cools too quickly, wrap it in a single layer of plastic freezer bag to slow the cooling.

### Use the library during normal capture

Under **Config → Image**, **Apply Dark Calibration Frames** enables dark subtraction. **Apply Bad Pixel Map Frames** is optional for pulsing pixels. Image processing selects compatible active masters with the nearest available temperature.

### Importing existing dark frames & bad pixel maps

You can import master darks and bad pixel maps created externally or restored from a backup using [indi-allsky-ctl](indi-allsky-ctl):

```bash
sudo indi-allsky-ctl import-darks
```

From a git checkout:

```bash
source virtualenv/indi-allsky/bin/activate && ./misc/import_darks_frames.py
```

---

## Using the web interface

Open **Info → Dark Library → Library Builder** with your local camera selected. Capture and library changes require the same permissions as saving configuration.

> **Keep indi-allsky running.** The builder pauses normal capture for you.

### Build your first library

#### 1. Temperature

Choose the temperature sensor and the allowed difference for matching existing masters.

- Readings update after camera exposures.
- Cooler targets come from **Config → Camera**.
- Cameras without a temperature sensor can still build a library using the existing no-sensor matching.

#### 2. Recommendation

Review the suggested plan and existing coverage. The builder uses your configured capture modes, gains, exposures, binning and image depth. It handles fixed gain, automatic gain, cameras with specific gain choices, and cameras without gain control.

**For a first run, keep the recommendation.**

#### 3. Capture

Review the estimated time and storage. Fully cover the camera, tick **The camera is fully covered**, and select **Start dark capture**.

### During capture

The current normal exposure finishes before dark capture begins. Progress shows capture, cooldown waits and processing.

**Cancel capture** keeps completed master sets and discards the current partial set. Cancellation may wait for a camera operation to finish. Camera settings are restored afterward and normal capture resumes.

### Optional adjustments

Open **Step 3 → Advanced options** to change the plan.

| Setting | What it does |
| --- | --- |
| **Library update** | Add missing sets, replace recommended sets, build or rebuild profiles, or edit the plan manually. |
| **Images per master set** | Default: 10. More source images take longer but reduce noise in the result. |
| **Combine source images** | Use **Average after removing outliers** for RAW, or **Average all images** for RGB data. A simple average is also available for RAW. |
| **Auto-gain spacing** | Finer spacing covers more gain levels, using more time and storage. Applies to continuous auto-gain. |
| **Longest exposure / Exposure interval / Exposure order** | Control the generated exposure list and which end is captured first. The interval is the step between exposure lengths. |

Configured libcamera/MQTT RGB profiles select **Average all images** automatically. For other RGB camera interfaces, select it manually.

#### Custom plans

Choose **Edit the plan manually** and adjust the capture rows.

- Gain and exposure fields each need at least one comma-separated value; for example, exposures `10, 5, 1`.
- Every gain/exposure combination is captured. Keep binning consistent with normal capture.
- **Restore recommended groups** discards manual row edits.

#### Sensor cooldown

Under **Delay between source images**, choose:

| Mode | Cooldown |
| --- | --- |
| **Fixed seconds** | The number of seconds you enter. Default: **0**, meaning no added wait. |
| **Match exposure time** | Waits 10 seconds after a 10-second exposure, for example. |

Cooldown applies after every source image, including the last in each master set. **The final cooldown overlaps creation of the dark and map**; the next set starts when both are finished. The estimated duration includes cooldown.

#### Several temperatures

Set **Run pattern → Repeat as temperature falls** to repeat the night plan after each chosen temperature drop.

- This needs a working temperature sensor and controlled cooling.
- Set **Stop at sensor temperature** to finish after a set at or below that reading, or leave it blank and cancel manually.
- The temperature-drop setting does not control cooling.

### Browse and maintain the library

Use **Dark Library** and **Bad Pixel Maps** to inspect stored files. In **Library Maintenance**, browse:

**Camera → Image profile → Temperature → Master sets**

Tick individual sets or combine selections from any level.

| Action | Effect |
| --- | --- |
| **Activate** | Makes selected sets available to image processing. |
| **Deactivate** | Stops their use but keeps the files; you can activate them again. |
| **Delete** | Permanently removes the selected files. Review the preview before confirming. |

Darks and their maps change together. Whole-library controls can activate all inactive sets, deactivate all active sets, or delete all inactive files across cameras.

---

## Using darks.py

The original `darks.py` command-line tool remains available alongside the web builder.

### Acquire dark frames

1. Fully cover the camera lens to block all light.
2. Stop the indi-allsky service:

    ```bash
    systemctl --user stop indi-allsky
    ```

3. Enter the indi-allsky git checkout:

    ```bash
    cd indi-allsky
    ```

4. Activate the Python virtual environment:

    ```bash
    source virtualenv/indi-allsky/bin/activate
    ```

5. Capture and stack the dark frames:

    ```bash
    # Use "sigmaclip" if your camera returns 16-bit RAW data
    ./darks.py sigmaclip

    # Use "average" if your camera returns RGB data
    ./darks.py average
    ```

The tool generates darks in 5-second increments at the configured gains for night, moonmode and day. It uses 10 source images for each master; change this with `--Count`.

| Maximum exposure | Approximate time to generate master darks |
| --- | --- |
| 15s | 20 minutes |
| 30s | 45 minutes |
| 45s | 1.5 hours |
| 60s | 2.5 hours |

### Options

| Command | What it does |
| --- | --- |
| `sigmaclip` | Capture and stack darks using sigma clipping |
| `average` | Capture and stack darks using average values |
| `tempaverage` | Capture a set at each 5°C temperature drop, using average stacking |
| `tempsigmaclip` | Capture a set at each 5°C temperature drop, using sigma clipping |
| `flush` | Delete all existing dark frames |

### Overrides

| Option | What it changes | Default |
| --- | --- | --- |
| `--Count` | Number of source images to stack for each exposure length | 10 |
| `--Time_delta` | Step between exposure lengths | 5 seconds |
| `--temp_delta` | Temperature drop between sets | 5°C |
| `--no-daytime` | Disable daytime dark capture | — |
| `--reverse` | Take images in reverse order | — |
| `--bitmax` | Maximum camera bit depth | 16 |
| `--gains` | Use a list of gains instead of those in the configuration | — |

### Temperature calibrated darks

Use `tempaverage` or `tempsigmaclip` to capture a full set at each 5°C decrease, with exposure lengths in 5-second increments. Daytime dark capture is automatically disabled in these modes.

1. As soon as you place the covered camera in the freezer, run `./darks.py tempsigmaclip` (or `./darks.py tempaverage`).
2. The tool captures the first set at the initial temperature.
3. It waits for a 5°C drop, then captures another set. This repeats until the camera reaches equilibrium with the freezer.
4. At the minimum temperature, stop the program manually with **Ctrl+C**.

If cooling was too fast, use the [cooling guidance](#temperature-and-cooling) above. Flush the darks and let the camera return to room temperature before restarting.

### Removing dark frames

The `flush` command deletes all existing dark frames:

```bash
# navigate to indi-allsky git checkout folder
cd indi-allsky
source virtualenv/indi-allsky/bin/activate
./darks.py flush
```
