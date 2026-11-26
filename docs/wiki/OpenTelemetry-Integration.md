# OpenTelemetry Integration

`indi-allsky` includes built-in OpenTelemetry (OTEL) instrumentation for **traces**, **metrics**, and **logs** exported over **OTLP/HTTP** (`opentelemetry-exporter-otlp-proto-http`).

When no OTLP endpoint is configured, OTEL remains in zero-overhead no-op mode.

---

## Configuration

OpenTelemetry is configured via environment variables in **`/etc/indi-allsky/indi-allsky.env`**. Both `indi-allsky.service` (capture, image, video, and sensor workers) and `gunicorn-indi-allsky.service` (Flask web UI and APIs) load `/etc/indi-allsky/indi-allsky.env` via systemd `EnvironmentFile`.

### 1. Edit `/etc/indi-allsky/indi-allsky.env`

Uncomment and set your OTLP/HTTP collector endpoint (for example, a local Grafana Alloy or OpenTelemetry Collector listening on port `4318`):

```ini
### OpenTelemetry (OTLP/HTTP)
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
OTEL_SERVICE_NAME=indi-allsky
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0
OTEL_METRIC_EXPORT_INTERVAL=60000
```

> **Note:** On systemd user-level installs (`setup.sh` default), the file is typically `/etc/indi-allsky/indi-allsky.env` or `~/.config/indi-allsky/indi-allsky.env` depending on your `$ALLSKY_ETC` directory.

### 2. Restart Services

```bash
systemctl --user restart indi-allsky gunicorn-indi-allsky
```

For system-level `.deb` installs:

```bash
sudo systemctl restart indi-allsky gunicorn-indi-allsky
```

---

## Supported Environment Variables

| Variable | Description | Example / Default |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Base OTLP/HTTP endpoint URL. Enables OTEL when set. | `http://127.0.0.1:4318` |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Optional override for trace export URL. | `http://127.0.0.1:4318/v1/traces` |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | Optional override for metric export URL. | `http://127.0.0.1:4318/v1/metrics` |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | Optional override for log export URL. | `http://127.0.0.1:4318/v1/logs` |
| `OTEL_SERVICE_NAME` | Overrides default `service.name` (`indi-allsky` / `indi-allsky-web`). | `indi-allsky` |
| `OTEL_TRACES_SAMPLER` | Trace sampling strategy. | `parentbased_traceidratio` |
| `OTEL_TRACES_SAMPLER_ARG` | Sampling ratio (`0.0` to `1.0`). | `1.0` |
| `OTEL_METRIC_EXPORT_INTERVAL` | Metric export interval in milliseconds. | `60000` |
| `OTEL_SDK_DISABLED` | Set to `true` to disable OTEL even if an endpoint is set. | `false` |

---

## Telemetry Collected

### Traces
- **Web / WSGI (`indi-allsky-web`):**
  - Inbound Flask HTTP requests (`FlaskInstrumentor`)
  - SQLAlchemy database queries (`SQLAlchemyInstrumentor`)
  - Outbound HTTP requests (`RequestsInstrumentor` — OIDC, SyncAPI, Allsky Map, YouTube, weather APIs)
- **Pipeline Workers (`indi-allsky`):**
  - `image.process` (`ImageWorker`)
  - `video.process_task` (`VideoWorker`, tagged with `task.id`)
  - `sensor.update` (`SensorWorker`)

### Metrics
| Metric | Type | Unit | Attributes |
|---|---|---|---|
| `indi_allsky.frames.captured` | Counter | `1` | `day_night` |
| `indi_allsky.exposure.duration` | Histogram | `s` | `day_night` |
| `indi_allsky.image.processing.duration` | Histogram | `s` | — |
| `indi_allsky.video.generation.duration` | Histogram | `s` | — |
| `indi_allsky.queue.depth` | Gauge | `1` | `queue` (`image_q`, `video_q`) |
| `indi_allsky.sensor.value` | Gauge | `1` | `sensor.name`, `sensor.slot` |

### Logs
- Attaches an OTEL `LoggingHandler` to the `indi_allsky` and `gunicorn.error` loggers alongside existing syslog/stderr handlers.
- Injects `trace_id` and `span_id` for log-to-trace correlation when logging inside active spans.

---

## Example Collector Receiver (Grafana Alloy)

```alloy
otelcol.receiver.otlp "default" {
  http {
    endpoint = "0.0.0.0:4318"
  }

  output {
    metrics = [otelcol.exporter.otlphttp.default.input]
    logs    = [otelcol.exporter.otlphttp.default.input]
    traces  = [otelcol.exporter.otlphttp.default.input]
  }
}
```
