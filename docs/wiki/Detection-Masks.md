# Detection Masks

By default, `indi-allsky` computes star counts and meteor lines within an automated central Region of Interest (RoI). However, terrestrial obstructions—such as trees, rooftops, power lines, and chimneys—interfere with analysis:
* Gaps in moving tree foliage produce spurious star detections.
* Rooflines, gutter contours, and power lines trigger false-positive meteor line detections during Hough line transformations.

Detection masks allow defining custom boundaries to restrict star and meteor detection strictly to unobstructed sky.

---

## 1. Mask Architecture

A detection mask is an 8-bit grayscale or monochrome PNG image matching the native sensor resolution:
* **White Pixels (`#FFFFFF` / 255)**: Active detection zones (analyzed for stars and meteors).
* **Black Pixels (`#000000` / 0)**: Masked zones (excluded from analysis).

> [!NOTE]
> The detection mask operates on raw sensor data prior to image flipping, rotation, or scaling. Consequently, the base image may appear inverted or mirrored relative to the final processed dashboard image.

---

## 2. Creation & Configuration Workflow

### Step 1: Download the Base Template
1. Navigate in the web dashboard to **Tools** → **Mask Base** (`https://<allsky-host>/indi-allsky/mask`).
2. Download `mask_base.png`. This image is generated automatically once the camera achieves a stable exposure.

### Step 2: Draw the Mask
1. Open `mask_base.png` in an image editor (e.g., GIMP, Photoshop, or Paint.NET).
2. Add a new layer and paint all non-sky features (trees, buildings, horizon structures) solid black (`#000000`).
3. Fill all open sky regions with solid white (`#FFFFFF`).
4. Ensure a small margin exists between high-contrast terrestrial boundaries and the sky zone to prevent edge artifacts.
5. Export the file as a PNG (e.g., `detection_mask.png`).

### Step 3: Install the Mask
Place the PNG mask file on the host filesystem:
* **Debian Package (`.deb`) Installations**:
  `/var/www/html/allsky/images/detection_mask.png` (or `/var/lib/indi-allsky/`)
* **Source / Git (`setup.sh`) Installations**:
  `/var/www/html/allsky/images/detection_mask.png`

> [!NOTE]
> Detection mask configuration under **Configuration** → **Processing** is an advanced feature visible only in **Expert Mode**. Enable Expert Mode via the toggle switch in the top configuration header.

In **Configuration** → **Processing**:
* Set `DETECT_MASK` to `detection_mask.png` (or provide the absolute path).

### Step 4: Validate Detection Tuning
1. In the web dashboard, open **Configuration** → **Image Processing** → **Detection Tuning**.
2. Enable **Run Detection** and select **Process**.
3. Inspect the rendered preview overlay to confirm detected stars and meteors reside exclusively within your unobstructed sky zones.