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

# Resume capture
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_secure_password"}' \
  https://allsky.local/indi-allsky/action/unpause
```