## Redirect URI
* `https://example.org/indi-allsky/oidc/callback`

## Config Variables

| Variable                  | Description |
| ------------------------- | ----------- |
| `OIDC_CLIENT_ID`          | OIDC Client ID provided by IdP |
| `OIDC_CLIENT_SECRET`      | OIDC Client Secret provided by IdP |
| `OIDC_DISCOVERY_ENDPOINT` |  Discovery endpoint for IdP |
| `OIDC_USERINFO_ENDPOINT`  | [Optional] User Info endpoint for IdP - This is only required for IdP that do not provide the endpoint in the discovery endpoint (eg GitHub) |
| `OIDC_USERNAME_CLAIM`     | The claim to be used to define the username in indi-allsky.  Common values are `preferred_username` or `email` |
| `OIDC_SCOPES`             | Requested scopes for OIDC authentication |
| `OIDC_PKCE`               | (Boolean) Enables Proof Key for Code Exchange |
| `OIDC_LOGO_URL`           | URL for IdP logo |
| `OIDC_ALLOWED_GROUPS`     | [Optional] List of OIDC managed groups allowed access to indi-allsky |
| `OIDC_ADMIN_GROUPS`       | [Optional] List of OIDC managed groups to be assigned admin access in indi-allsky |
| `OIDC_ALLOWED_USERS`      | [Optional] List of users to allowed access.  Can be used when the IdP does not provide group functions |
| `OIDC_ADMIN_USERS`        | [Optional] List of users to be assigned admin access.  Can be used when the IdP does not provide group |functions


## GitHub
GitHub requires a manual `userinfo` endpoint since it is not advertised in the discovery endpoint.  The username claim can be either `login` or `email`

```json
  "LOCAL_AUTH_ENABLE" : true,
  "OIDC_ENABLE" : true,
  "OIDC_PROVIDER_NAME" : "GitHub",
  "OIDC_CLIENT_ID" : "xxxxxxxxxxxxxxxxxxxx",
  "OIDC_CLIENT_SECRET" : "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
  "OIDC_DISCOVERY_ENDPOINT" : "https://github.com/login/oauth/.well-known/openid-configuration",
  "OIDC_USERINFO_ENDPOINT" : "https://api.github.com/user",
  "OIDC_USERNAME_CLAIM" : "login",
  "OIDC_SCOPES" : "openid email profile offline_access",
  "OIDC_PKCE" : true,
  "OIDC_LOGO_URL" : "",
  "OIDC_ALLOWED_GROUPS" : [],
  "OIDC_ADMIN_GROUPS" : [],
  "OIDC_ADMIN_USERS" : [
    "github_username"
  ],
  "OIDC_ALLOWED_USERS" : [
    "github_username"
  ],
```

## Google
```json
  "LOCAL_AUTH_ENABLE" : true,
  "OIDC_ENABLE" : true,
  "OIDC_PROVIDER_NAME" : "Google",
  "OIDC_CLIENT_ID" : "xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.apps.googleusercontent.com",
  "OIDC_CLIENT_SECRET" : "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
  "OIDC_DISCOVERY_ENDPOINT" : "https://accounts.google.com/.well-known/openid-configuration",
  "OIDC_USERINFO_ENDPOINT" : "",
  "OIDC_USERNAME_CLAIM" : "email",
  "OIDC_SCOPES" : "openid email profile",
  "OIDC_PKCE" : true,
  "OIDC_LOGO_URL" : "",
  "OIDC_ALLOWED_GROUPS" : [],
  "OIDC_ADMIN_GROUPS" : [],
  "OIDC_ADMIN_USERS" : [
    "example@gmail.com"
  ],
  "OIDC_ALLOWED_USERS" : [
    "example@gmail.com"
  ],
```