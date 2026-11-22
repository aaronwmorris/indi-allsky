# Image Format & PNG Compression Performance

`indi-allsky` supports saving primary capture images in either JPEG (`.jpg`) or PNG (`.png`) format. Choosing between these formats involves tradeoffs between image fidelity, file storage size, and processor encoding overhead.

Format and compression settings are configured under **Configuration** → **Image Processing** → **Image File Settings**.

---

## 1. PNG vs JPEG Format Tradeoffs

* **JPEG (`.jpg`)**:
  * **Advantages**: Highly optimized hardware and SIMD-accelerated encoding (`simplejpeg` / libjpeg-turbo). Fast compression (typically $< 100$ milliseconds per frame). Compact storage footprint.
  * **Disadvantages**: Lossy compression. High-contrast star borders may exhibit minor 8x8 DCT compression ringing.
* **PNG (`.png`)**:
  * **Advantages**: Lossless compression. Preserves pixel values and color depth without artifacting.
  * **Disadvantages**: Substantially higher CPU utilization during deflate/zlib compression. Uncompressed 16-bit PNG frames require significant disk space and transfer bandwidth.

---

## 2. PNG Compression Levels Benchmarks

The PNG specification defines compression levels from `0` (uncompressed) to `9` (maximum compression). On embedded ARM single-board computers (such as the Raspberry Pi 4 and 5), levels above `5` introduce severe latency that can exceed the capture interval:

| PNG Level | Average Compression Time (1080p Frame) | CPU Load Impact | Recommendation |
|---|---|---|---|
| **Level 0** | $< 0.1$ seconds | Minimal | Uncompressed. Creates massive files; not recommended. |
| **Level 1 – 3** | $0.3$ – $0.8$ seconds | Low | **Recommended for PNG**. Rapid encoding with acceptable compression ratios. |
| **Level 4 – 5** | $1.2$ – $1.8$ seconds | Moderate | Balanced. Suitable if exposure interval $\ge 15$ seconds. |
| **Level 6** | $2.5$ – $3.5$ seconds | High | Noticeable queue latency on multi-frame sequences. |
| **Level 7 – 8** | $5.0$ – $18.0$ seconds | Severe | Can cause image processing queues to fall behind capture loops. |
| **Level 9** | $25.0$ – $38.0$ seconds | Extreme | **Do not use**. Compressing a single frame can take longer than the entire exposure interval. |

---

## 3. Operational Recommendations

1. **Default Recommendation**: Utilize **JPEG** with quality set between `85` and `95`.
2. **If Lossless Output is Required**: Select **PNG** and set compression level to **`1`**, **`2`**, or **`3`**. Levels 7 through 9 yield minimal additional file size reduction (often $< 3\%$) while increasing CPU encoding duration by several hundred percent.
3. **Astrophotographic FITS Storage**: If scientific pixel analysis is required, leave standard images as JPEG and enable **Save FITS** or **Save RAW** in camera settings to archive unprocessed calibration frames.