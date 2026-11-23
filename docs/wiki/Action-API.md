# Action API Reference

The Action API permits remote management and automation systems (such as Home Assistant, Node-RED, or shell scripts) to control `indi-allsky` execution states using authenticated HTTP POST requests.

Action requests operate asynchronously: the API validates credentials and enqueues a priority task into the daemon's internal `taskqueue` table (`IndiAllSkyDbTaskQueueTable`). The daemon executes the task on the subsequent loop iteration.

---

## Authentication & Network Access Controls

Every request must satisfy two strict security requirements:

1. **User Credentials**:
   * The request payload must contain valid credentials for an administrative account (`is_admin=True` in `IndiAllSkyDbUserTable`). Passwords are verified using Argon2 hashing.
2. **Admin Network Restriction**:
   * The requesting client's IP address must reside within the CIDR subnets defined by `ADMIN_NETWORKS` in `/etc/indi-allsky/flask.json`:
   ```json
   "ADMIN_NETWORKS": [
     "127.0.0.1/32",
     "10.0.0.0/8",
     "172.16.0.0/12",
     "192.168.0.0/16"
   ]
   ```
   Requests arriving from unauthorized IP addresses receive an HTTP 400 `permission denied` response.

---

## Endpoints

| Endpoint | Method | Action | HTTP Response Codes |
|---|---|---|---|
| `/indi-allsky/action/pause` | `POST` | Pauses camera image acquisition. | `201 Created`: Pause task enqueued.<br>`200 OK`: Capture was already paused.<br>`400 Bad Request`: Authentication or network authorization failure. |
| `/indi-allsky/action/unpause` | `POST` | Resumes camera image acquisition. | `201 Created`: Unpause task enqueued.<br>`200 OK`: Capture was already active.<br>`400 Bad Request`: Authentication or network authorization failure. |

---

## Request Format & Examples

### JSON Payload
All requests require the `Content-Type: application/json` header and a JSON body containing administrative credentials:

```json
{
  "username": "admin",
  "password": "your_secure_password"
}
```

### cURL Invocation
```bash
# Pause capture
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_secure_password"}' \
  https://allsky.local/indi-allsky/action/pause

# resume capture
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_secure_password"}' \
  https://allsky.local/indi-allsky/action/unpause
```

---

## WebSocket Control (`/ws/control`) — Custom Timelapses

The authenticated `/ws/control` WebSocket endpoint (authenticated via `api_key` / `token` query parameter, `X-API-Key` header, `Authorization: Bearer <key>`, or an active admin session) supports queuing custom time-range timelapses (stored in `IndiAllSkyDbMiniVideoTable` and visible in **Mini Timelapses**) as well as polling task status.

### `generate_custom_timelapse`

Provide either explicit `start_time` / `end_time` (ISO-8601 strings or Unix timestamps) or a rolling `hours` window (`0 < hours <= 168`):

```json
{
  "action": "generate_custom_timelapse",
  "camera_id": 1,
  "hours": 24,
  "framerate": 25,
  "bitrate": "5000k",
  "source_type": "standard",
  "note": "Rolling 24h timelapse"
}
```

Response:

```json
{
  "event": "command_result",
  "timestamp": 1763868000.0,
  "data": {
    "action": "generate_custom_timelapse",
    "status": "queued",
    "task_id": 42,
    "camera_id": 1,
    "start_date": "2026-11-22T12:00:00",
    "end_date": "2026-11-23T12:00:00"
  }
}
```

### `get_task_status`

Poll a queued task by `task_id`:

```json
{
  "action": "get_task_status",
  "task_id": 42
}
```

Response:

```json
{
  "event": "task_status",
  "timestamp": 1763868120.0,
  "data": {
    "task_id": 42,
    "queue": "VIDEO",
    "state": "SUCCESS",
    "result": "Generated timelapse (mini_video_id=15): ..."
  }
}
```