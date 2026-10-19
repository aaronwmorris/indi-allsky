# OpenID Connect (OIDC / SSO) Authentication

`indi-allsky` supports Single Sign-On (SSO) authentication using OpenID Connect (OIDC) and OAuth 2.0. This allows integrating authentication with identity providers such as Keycloak, Authentik, Authelia, Google Workspace, and GitHub.

---

## 1. Redirect URI

Configure the authorized redirect URI in your Identity Provider (IdP):

```
https://<your-allsky-domain>/indi-allsky/oidc/callback
```

> [!IMPORTANT]
> The redirect URI must use HTTPS unless testing strictly on `localhost`. If `indi-allsky` operates behind a reverse proxy (e.g. Caddy or Nginx), ensure proxy headers (`X-Forwarded-Proto: https`) are transmitted so callback validation succeeds.

---

## 2. Configuration Location

OIDC infrastructure credentials reside in the system Flask configuration file:

* **Debian Package (`.deb`) Installations**: `/etc/indi-allsky/flask.json`
* **Source / Git (`setup.sh`) Installations**: Defined by the `INDI_ALLSKY_FLASK_CONFIG` environment variable (defaults to `/etc/indi-allsky/flask.json`).

After updating `flask.json`, restart the web application service:
* **Debian Package Installations**:
  ```bash
  sudo systemctl restart gunicorn-indi-allsky.socket gunicorn-indi-allsky.service
  ```
* **Source / Git Installations**:
  ```bash
  sudo systemctl restart gunicorn-indi-allsky
  ```

---

## 3. Configuration Reference

| Parameter | Type | Default | Description |
|---|---|---|---|
| `OIDC_ENABLE` | Boolean | `false` | Enables OpenID Connect authentication. |
| `OIDC_PROVIDER_NAME` | String | `""` | Human-readable provider label displayed on the login button. |
| `OIDC_CLIENT_ID` | String | `""` | Client identifier issued by the IdP. |
| `OIDC_CLIENT_SECRET` | String | `""` | Client secret issued by the IdP. |
| `OIDC_DISCOVERY_ENDPOINT` | String | `""` | OpenID configuration endpoint (`.../.well-known/openid-configuration`). |
| `OIDC_USERINFO_ENDPOINT` | String | `""` | (Optional) Explicit userinfo endpoint for providers that omit it from discovery (e.g., GitHub). |
| `OIDC_USERNAME_CLAIM` | String | `"preferred_username"` | Token claim mapped to the local username (`preferred_username`, `email`, or `login`). |
| `OIDC_SCOPES` | String | `"openid email profile offline_access"` | OAuth 2.0 scopes requested during authorization. |
| `OIDC_PKCE` | Boolean | `true` | Enables Proof Key for Code Exchange (RFC 7636). Recommended for all modern IdPs. |
| `OIDC_LOGO_URL` | String | `""` | Optional URL to an image or SVG icon displayed on the SSO login button. |
| `OIDC_ALLOWED_GROUPS` | List | `[]` | List of IdP group names permitted to log in. An empty list allows all authenticated users. |
| `OIDC_ADMIN_GROUPS` | List | `[]` | List of IdP group names granted administrator privileges (`is_admin=True`). |
| `OIDC_ALLOWED_USERS` | List | `[]` | Specific usernames/emails allowed login (useful if the IdP lacks group claims). |
| `OIDC_ADMIN_USERS` | List | `[]` | Specific usernames/emails granted administrator privileges. |
| `LOCAL_AUTH_ENABLE` | Boolean | `true` | Retains local username/password login alongside OIDC. |

---

## 4. Identity Provider Examples

### Keycloak / Authentik (Standard OIDC)
```json
{
  "LOCAL_AUTH_ENABLE": true,
  "OIDC_ENABLE": true,
  "OIDC_PROVIDER_NAME": "Keycloak",
  "OIDC_CLIENT_ID": "indi-allsky",
  "OIDC_CLIENT_SECRET": "your-client-secret",
  "OIDC_DISCOVERY_ENDPOINT": "https://auth.example.com/realms/master/.well-known/openid-configuration",
  "OIDC_USERNAME_CLAIM": "preferred_username",
  "OIDC_SCOPES": "openid email profile offline_access",
  "OIDC_PKCE": true,
  "OIDC_ALLOWED_GROUPS": ["allsky-users", "allsky-admins"],
  "OIDC_ADMIN_GROUPS": ["allsky-admins"],
  "OIDC_ALLOWED_USERS": [],
  "OIDC_ADMIN_USERS": []
}
```

### Google Workspace / Cloud Identity
```json
{
  "LOCAL_AUTH_ENABLE": true,
  "OIDC_ENABLE": true,
  "OIDC_PROVIDER_NAME": "Google",
  "OIDC_CLIENT_ID": "your-client-id.apps.googleusercontent.com",
  "OIDC_CLIENT_SECRET": "your-client-secret",
  "OIDC_DISCOVERY_ENDPOINT": "https://accounts.google.com/.well-known/openid-configuration",
  "OIDC_USERNAME_CLAIM": "email",
  "OIDC_SCOPES": "openid email profile",
  "OIDC_PKCE": true,
  "OIDC_ADMIN_USERS": ["observatory-admin@gmail.com"],
  "OIDC_ALLOWED_USERS": ["observatory-admin@gmail.com", "member@gmail.com"]
}
```

### GitHub
GitHub OAuth does not publish the userinfo endpoint in standard discovery:
```json
{
  "LOCAL_AUTH_ENABLE": true,
  "OIDC_ENABLE": true,
  "OIDC_PROVIDER_NAME": "GitHub",
  "OIDC_CLIENT_ID": "your-github-client-id",
  "OIDC_CLIENT_SECRET": "your-github-client-secret",
  "OIDC_DISCOVERY_ENDPOINT": "https://github.com/login/oauth/.well-known/openid-configuration",
  "OIDC_USERINFO_ENDPOINT": "https://api.github.com/user",
  "OIDC_USERNAME_CLAIM": "login",
  "OIDC_SCOPES": "openid email profile",
  "OIDC_PKCE": true,
  "OIDC_ADMIN_USERS": ["your_github_username"],
  "OIDC_ALLOWED_USERS": ["your_github_username"]
}
```