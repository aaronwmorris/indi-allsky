# Overview
The Action API allows you to control the behavior of indi-allsky via HTTP POST requests.

Most actions are asynchronous, therefore, when the HTTP request is finished, that does NOT mean the action has fully completed.  The action may require 1-3 minutes to complete.

## Data format
Data must be posted in JSON format with the username and password attributes

```json
{
  "username" : "foo",
  "password" : "bar"
}
```

### curl example
```bash
curl \
  --insecure \
  --include \
  --header "Content-Type: application/json" \
  --request POST \
  --data '{"username": "foo", "password": "bar"}' \
  https://localhost/indi-allsky/action/pause
```

## Endpoints
| Endpoint | Description |
| -------- | ----------- |
| /indi-allsky/action/pause     | Pauses image capture |
| /indi-allsky/action/unpause   | Unpauses image capture |