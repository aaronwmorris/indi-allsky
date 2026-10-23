# Overview
indi-allsky utilizes [ffmpeg](https://www.ffmpeg.org/) to convert a sequence of captured frames into an H.264/H.265 or WebM timelapse video. Timelapses are compiled automatically at dawn for nighttime sequences and dusk for daytime sequences, or triggered on demand through the web interface archive viewer.

For intermediate short-interval rolling video clips, refer to [`Mini-Timelapses`](Mini-Timelapses.md).

## Key Settings
* `Framerate` — The target playback frame rate (frames per second). Typical astronomical allsky timelapses operate at 24 to 30 fps.
* `Bitrate` — Target encoding bitrate (e.g. `5000k` for 1080p, `10000k` to `15000k` for 4K UHD).
* `Scaling` — Scales the video resolution down relative to native sensor dimensions. Scaling significantly reduces RAM usage during the ffmpeg encoding phase.
* `Codec` — Video encoder. `x264` (libx264) is the recommended default.
* `Skip frames` — Skips an initial number of frames during dawn/dusk transitions to avoid flicker caused by exposure settling.

---

## Technical Constraints on FFMPEG Scaling

A critical requirement of H.264/H.265 encoders (YUV420p chroma subsampling) is that **both horizontal and vertical output dimensions must be even integers (divisible by 2)**. If an arbitrary percentage scaling factor yields odd pixel dimensions, ffmpeg aborts with an unrecoverable filtergraph error.

The camera settings provide discrete integer scaling options and dedicated sensor presets (such as Sony IMX477 / Raspberry Pi HQ Camera) to guarantee even dimensions.

---

## Memory Architecture — x264 Encoding

Peak memory consumption occurs during the ffmpeg multi-threaded encoding pipeline. Systems with limited physical memory (1GB–2GB SBCs) must utilize scaling to remain within RAM budgets:

| Output Resolution  | Recommended Memory | Minimum Memory (with Swap) | FFMPEG Process RSS |
| ------------------ | ------------------ | -------------------------- | ------------------ |
| 852 x 480 (0.4MP)  | 1 GB               | <1 GB with swap            | ~200 MB            |
| 1280 x 960 (1.2MP) | 2 GB               | 1 GB + 1 GB swap           | ~400 MB            |
| 1920 x 1080 (2MP)  | 2 GB               | 1 GB + 1 GB swap           | ~600 MB            |
| 3840 x 2160 (8MP)  | 4 GB               | 2 GB + 1 GB swap           | ~1.7 GB            |
| 3008 x 3008 (9MP)  | 4 GB               | 2 GB + 1 GB swap           | ~1.8 GB            |
| 4056 x 3040 (12MP) | 4 GB               | 2 GB + 2 GB swap           | ~2.5 GB            |
| 6224 x 4168 (26MP) | 8 GB               | 4 GB                       | ~5.0 GB            |
| 9152 x 6944 (64MP) | 16 GB              | 8 GB                       | ~12.0 GB           |

---

## Video Codec Targets

| Codec | Description & Platform Notes |
|---|---|
| `x264` | Standard software H.264 encoder. Universal browser compatibility. |
| `x265 hevc` | H.265 encoder. Higher CPU utilization and memory footprint. Limited browser playback support without transcoding. |
| `webm` | VP8/VP9 open web format. |
| `h264 v4l2m2m` | Raspberry Pi hardware-accelerated V4L2 M2M encoder (limited to 1920x1920 maximum resolution). |
| `h264 QSV` | Intel Quick Sync Video hardware acceleration. |
| `h264 NVENC` | NVIDIA hardware NVENC acceleration. |
| `h264 VAAPI` | VA-API hardware acceleration (Intel/AMD). |

> [!WARNING]
> Hardware-accelerated targets (`NVENC`, `QSV`, `VAAPI`) require host GPU driver enablement and non-free encoder packages installed on the system.

---

## Timelapse Pre-Processors

| Pre-Processor | Description | Resource Considerations |
|---|---|---|
| **Standard** | Frames compiled as captured without geometric or overlay modifications. | Baseline resources. |
| **Wrapped Keogram** | Projects the daily keogram circularly along the perimeter of the circular sky view. | High CPU/disk I/O. Reads each frame, warps the radial keogram slice, and writes temporary frames to disk scratch space (1–4 GB). Recommend minimum 4 GB RAM. |

---

## Troubleshooting & Diagnostics

If timelapse compilation fails, activate **Generate Debug Report** under **Configuration -> Timelapse**.

When enabled, ffmpeg generates an execution trace log:
* On Debian Package (`.deb`) systems: `/var/lib/indi-allsky/ffmpeg-report-*.log`
* On Source / Git systems: `~/.indi-allsky/` or home folder of the service user.

Inspect active video encoding tasks and failures in the database task queue:
```sql
SELECT id, queue, state, createDate FROM taskqueue WHERE queue = 'video' ORDER BY id DESC LIMIT 5;
```