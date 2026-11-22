# Fisheye & Allsky Lenses

Selecting an appropriate optical lens requires matching the lens projection circle diameter to the physical sensor dimensions of your camera.

If the lens image circle is smaller than the sensor, the full circular fisheye horizon is visible with black margins surrounding the circle. If the image circle is larger than the sensor, the view will be cropped to a rectangular field of view.

---

## Lens Specifications & Sensor Pairing Matrix

| Lens | Field of View (FoV) | Focal Length | Focal Ratio | Aperture | Image Circle Diameter | Ideal Sensor Format & Cameras |
|---|---|---|---|---|---|---|
| **ZWO 2.1mm** | $150^\circ$ | 2.1mm | f/2.0 | 1.05mm | 6.7mm | 1/3" & 1/2.8" (ZWO ASI120, ASI224, ASI290, ASI462) |
| **ZWO 2.5mm** | $170^\circ$ | 2.5mm | f/1.2 | 2.08mm | 6.7mm | 1/3" & 1/2.8" (ASI224MC, ASI462MC, ASI662MC) |
| **Arecont 1.55mm** | $180^\circ$ | 1.55mm | f/2.0 | 0.78mm | 4.8mm | 1/2.3" (Raspberry Pi HQ / IMX477, IMX378) |
| **StarDot 1.55mm** | $185^\circ$ | 1.55mm | f/1.5 | 1.03mm | 4.8mm | 1/2.3" (Raspberry Pi HQ / IMX477) |
| **M12 1.7mm** | $180^\circ$ | 1.7mm | f/2.0 | 0.85mm | 5.6mm | 1/2" – 1/1.8" (ASI178, ASI678MC, ASI676MC) |
| **M12 1.8mm** | $180^\circ$ | 1.8mm | f/2.0 | 0.90mm | 6.9mm | 1/1.8" (Sony IMX178, IMX678, IMX676) |
| **Meike 3.5mm f/2.8** | $220^\circ$ | 3.5mm | f/2.8 | 1.25mm | 12.5mm | 1" & Micro Four Thirds (MFT) (ASI183, ASI294, ASI533) |
| **Camera Module 3 Wide** | $120^\circ$ | 2.75mm | f/2.2 | 1.25mm | Full sensor | Raspberry Pi Camera Module 3 Wide (IMX708) |
| **Camera Module 3 Standard**| $75^\circ$ | 4.74mm | f/1.8 | 2.63mm | Full sensor | Raspberry Pi Camera Module 3 (IMX708) |
| **Hawkeye 64MP AF** | $84^\circ$ | 5.1mm | f/1.8 | 2.83mm | Full sensor | Arducam 64MP Hawkeye |

---

## Mount Considerations

* **M12 Mount (S-Mount)**: The standard thread for embedded camera boards and security lenses ($M12 \times 0.5$). Requires an M12-to-CS or M12-to-C adapter ring when used with standard astronomy cameras.
* **CS-Mount**: Back-focus distance of 12.526 mm. Used natively by the Raspberry Pi HQ Camera and many industrial CMOS housings.
* **C-Mount**: Back-focus distance of 17.526 mm (5 mm deeper than CS-mount). C-mount lenses attach to CS cameras using a 5 mm spacer ring.