# Model Context Protocol (MCP) Server

INDI Allsky includes a native **Model Context Protocol (MCP)** server (`indi-allsky-mcp`). MCP is an open standard that enables AI assistants (such as Google Antigravity, Claude Desktop, Cursor, Roo Code, and Cline) to safely and securely interact with your observatory system in real-time.

With the MCP server enabled, an AI agent can:
- **Inspect & Tune Image Processing**: Simulate processing curves, tune stretch parameters (`MODE1_GAMMA`, `MODE2_MIDTONES`, `CLAHE`), optimize star detection, and apply configuration changes with automated rollback protection.
- **Analyze Astrometry & Optics**: Calculate lens distortion, focal length, True North orientation alignment, and star sharpness curves.
- **Control Hardware Peripherals**: Read temperature/humidity/SQM telemetry, command dew heaters and enclosure fans, and run stepper motor autofocus sweeps.
- **Audit Calibration & Quality**: Inspect dark frame libraries for temperature/gain coverage gaps, generate bad pixel maps, and analyze historical sky conditions.
- **Monitor System Health & Queue**: Inspect task queues, check Raspberry Pi hardware throttling/undervoltage flags, stream application logs, and inject desktop notifications.

---

## 1. Quick Start & Service Management

By default, the MCP server is installed but **not enabled or started** during package installation. You must explicitly start or enable it.

### Using `indi-allsky-ctl`

The [`indi-allsky-ctl`](indi-allsky-ctl) utility provides built-in commands to control the background daemon:

```bash
# Enable and start the MCP daemon on system boot:
sudo indi-allsky-ctl mcp enable

# Check daemon running status:
indi-allsky-ctl mcp status

# Follow real-time daemon logs:
indi-allsky-ctl mcp logs

# Stop and restart daemon:
sudo indi-allsky-ctl mcp restart

# Stop and disable the daemon:
sudo indi-allsky-ctl mcp disable
```

### Running Interactively (Foreground)

You can also run the server directly in the foreground for debugging:

```bash
# Run with default SSE transport on 0.0.0.0:8000:
indi-allsky-ctl mcp run

# Run with custom host and port:
indi-allsky-ctl mcp run --host 127.0.0.1 --port 8080

# Run in stdio mode (for local subprocess transport):
indi-allsky-ctl mcp run --transport stdio
```

---

## 2. Connecting AI Clients

### Network Endpoint (SSE Transport)

When running as a service, the server listens for **Server-Sent Events (SSE)** at:
```
http://<ALLSKY_IP_OR_HOSTNAME>:8000/sse
```

### Client Configuration Examples

#### Google Antigravity (`~/.gemini/config/mcp_config.json`)
```json
{
  "mcpServers": {
    "indi-allsky": {
      "serverUrl": "http://192.168.1.100:8000/sse"
    }
  }
}
```

#### Claude Desktop (`claude_desktop_config.json`)
Using an SSH tunnel or local stdio invocation:
```json
{
  "mcpServers": {
    "indi-allsky": {
      "command": "ssh",
      "args": [
        "user@allsky.local",
        "indi-allsky-ctl",
        "mcp",
        "run",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

---

## 3. Tool Catalog Reference

The MCP server exposes 38 specialized tools grouped by subsystem:

### Configuration Subsystem
| Tool | Description |
| :--- | :--- |
| `get_config` | Fetch active configuration or a specific section dictionary. |
| `update_config` | Apply configuration overrides with automatic database revision history tracking. |
| `list_config_history` | Retrieve historical configuration snapshots and audit notes. |
| `rollback_config` | Roll back system configuration to a previous revision ID. |

### Image Catalog & Archive
| Tool | Description |
| :--- | :--- |
| `get_latest_image` | Retrieve latest captured light frame metadata, SQM, star count, and file paths. |
| `query_image_history` | Filter historical exposures by star count, sun altitude, or day date. |
| `get_raw_fits_catalog` | List available raw 16-bit FITS captures stored on disk. |
| `get_image_metadata` | Inspect EXIF headers, camera parameters, and processing records for a specific image. |

### Image Processing Simulator
| Tool | Description |
| :--- | :--- |
| `simulate_processing` | Execute full in-memory image pipeline simulation on a raw FITS file with custom stretch/denoise parameters. |
| `evaluate_image_quality` | Calculate SNR, star count yield, background ADU noise floor, and composite quality scores. |
| `compare_simulation_variants` | Benchmark multiple candidate processing parameter dictionaries against the same raw frame and rank results. |
| `detect_lines_and_meteors` | Run Hough transform detection to identify meteor streaks and satellite trails. |

### Astrometry & Optics
| Tool | Description |
| :--- | :--- |
| `solve_lens_geometry` | Execute astrometric plate solving to derive optical focal length, field-of-view, and center offsets. |
| `align_cardinal_directions` | Derive True North orientation error and cardinal label placement. |

### Hardware & Peripherals
| Tool | Description |
| :--- | :--- |
| `get_sensor_telemetry` | Read real-time environmental sensors (temperature, humidity, dew point, SQM, ambient lux). |
| `control_dew_heater` | Command dew heater power duty cycle (0-100%) and operational mode. |
| `control_enclosure_fan` | Command enclosure cooling fan target temperature and manual speed. |
| `get_focuser_position` | Query current stepper motor focuser step position and limits. |
| `move_focuser` | Command relative or absolute focuser step motion. |
| `run_autofocus_sweep` | Execute automated V-curve focus sweep to identify optimal star sharpness point. |
| `set_capture_pause` | Temporarily pause or resume camera image acquisition. |

### Calibration & Dark Frames
| Tool | Description |
| :--- | :--- |
| `audit_dark_library` | Audit dark frame library coverage across temperature bins, gains, and exposures. |
| `generate_bad_pixel_map` | Create static bad pixel map from master dark frames. |
| `generate_master_darks` | Trigger master dark frame stacking for specified temperature bins. |

### Ephemeris & Space Weather
| Tool | Description |
| :--- | :--- |
| `get_aurora_telemetry` | Read NOAA Ovation aurora probability, solar wind velocity, and geomagnetic Kp-index. |
| `get_satellite_passes` | Predict upcoming visible passes for ISS, Tiangong, HST, and custom satellites. |
| `update_orbital_elements` | Refresh Two-Line Element (TLE) ephemeris data from CelesTrak. |
| `query_air_traffic` | Fetch local ADS-B aircraft positions within optical field-of-view. |

### Operations & Diagnostics
| Tool | Description |
| :--- | :--- |
| `get_system_logs` | Retrieve recent log lines from application, web, or INDI server logs. |
| `get_hardware_throttling` | Check Raspberry Pi CPU throttling, undervoltage, and frequency capping flags. |
| `inspect_task_queue` | List pending and running background video/timelapse generation tasks. |
| `cancel_task` | Cancel a running or queued background task. |
| `trigger_cloud_sync` | Initiate immediate cloud storage sync (SFTP, S3, Sync API). |
| `send_notification` | Inject user alert notification into the database and UI banner. |
| `generate_custom_timelapse` | Render custom MP4 timelapse for a specified date range. |
| `render_keogram` | Render full night keogram from captured images. |
| `generate_startrails` | Generate composite star trail image with threshold masking. |
| `backup_database` | Trigger immediate database backup snapshot. |

---

## 4. Context Resources

Clients can subscribe to or read standardized read-only URI resources:

- `allsky://config/active` — Complete active system configuration JSON.
- `allsky://camera/status` — Primary camera connection state, driver capabilities, and sensor properties.
- `allsky://images/latest` — Metadata of the most recently acquired image.
- `allsky://telemetry/environment` — Real-time environmental sensor metrics (temperature, humidity, SQM).
- `allsky://queue/active` — Active and queued background operations.
- `allsky://logs/recent` — Recent lines from the primary application log.

---

## 5. Guided Prompt Workflows

Predefined interactive prompt workflows guide AI agents through complex diagnostic tasks:

1. `optimize_image_pipeline` — Systematic parameter tuning for dark sky vs. moonlit conditions.
2. `diagnose_capture_quality` — End-to-end capture health, SNR evaluation, and detection verification.
3. `diagnose_optics_and_focus` — Astrometric plate solving, True North verification, and focus V-curve analysis.
4. `audit_observatory_health` — Environmental checks, dark library gap identification, and thermal throttling review.
5. `diagnose_system_logs` — Automated error pattern recognition across application and INDI server logs.

---

## 6. Security Considerations

> [!WARNING]
> By default, the MCP server allows configuration modification, hardware actuation, and system command triggering.
> - **Private Network Only**: Do not expose port 8000 directly to the public Internet without a reverse proxy, VPN (e.g. WireGuard or Tailscale), or firewall rules.
> - **Local Access**: For remote AI agents on external workstations, use an SSH tunnel (`ssh -L 8000:localhost:8000 user@allsky.local`) or stdio transport.
