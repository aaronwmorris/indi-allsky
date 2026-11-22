# Operating in Unencrypted HTTP Mode

By default, `indi-allsky` enforces HTTPS. Any unencrypted HTTP request is redirected to HTTPS with secure session cookies and HTTP Strict Transport Security (HSTS) headers.

Disabling HTTPS is typically required only when placing `indi-allsky` behind an external edge reverse proxy (e.g. Cloudflare Tunnels, Traefik, or HAProxy) that handles TLS termination externally, or on isolated offline local networks.

---

## 1. Disable Secure Cookies in Flask

When accessing over plain HTTP, browsers will discard cookies marked with the `Secure` flag, preventing successful logins:

1. Edit `/etc/indi-allsky/flask.json`:
   ```json
   "SESSION_COOKIE_SECURE": false,
   "REMEMBER_COOKIE_SECURE": false,
   ```
2. Restart the Gunicorn web service:
   * **Debian Package (`.deb`) Installations**:
     ```bash
     sudo systemctl restart gunicorn-indi-allsky.socket gunicorn-indi-allsky.service
     ```
   * **Source / Git (`setup.sh`) Installations**:
     ```bash
     sudo systemctl restart gunicorn-indi-allsky
     # Or for user-level systemd: systemctl --user restart gunicorn-indi-allsky
     ```

---

## 2. Configure the Reverse Proxy

### Caddy (Default Reverse Proxy)
Edit `/etc/caddy/Caddyfile` (or `/etc/caddy/caddy_indi-allsky.conf`):

1. Remove or comment out the `http://` redirect block:
   ```caddy
   # Comment out the HTTP redirect:
   # http:// {
   #     redir https://{host}:8000{uri}
   # }
   ```
2. Change the `https://` block to listen directly on HTTP:
   ```caddy
   :80 {
       # Comment out the TLS certificate declaration
       # tls /etc/caddy/ssl/indi-allsky_caddy.pem /etc/caddy/ssl/indi-allsky_caddy.key

       redir / /indi-allsky/

       handle /indi-allsky/images/* {
           root * /var/www/html/allsky/images
           uri strip_prefix /indi-allsky/images
           file_server
       }

       handle /indi-allsky/static/* {
           root * /usr/share/indi-allsky/indi_allsky/flask/static
           uri strip_prefix /indi-allsky/static
           file_server
       }

       handle /indi-allsky/* {
           reverse_proxy unix//run/gunicorn-indi-allsky/socket
       }
   }
   ```
3. Reload Caddy:
   ```bash
   sudo systemctl reload caddy
   ```

### Nginx
Edit `/etc/nginx/sites-enabled/indi-allsky.conf`:

1. Comment out the redirect and HSTS header:
   ```nginx
   server {
       listen 80;
       root /var/www/html/allsky;

       # Comment out HTTPS redirect:
       # return 302 https://$host$request_uri;

       # Comment out HSTS header:
       # add_header Strict-Transport-Security "max-age=604800; includeSubDomains" always;
   }
   ```
2. Reload Nginx:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

### Apache
Edit `/etc/apache2/sites-enabled/indi-allsky.conf`:

1. In the `<VirtualHost *:80>` block, comment out the rewrite condition and HSTS header:
   ```apache
   # RewriteCond "%{HTTPS}" off
   # RewriteRule "^/(.*)" "https://%{SERVER_NAME}:443/$1" [R,L]
   # Header always set Strict-Transport-Security "max-age=604800; includeSubDomains"
   ```
2. Reload Apache:
   ```bash
   sudo systemctl reload apache2
   ```

---

## 3. Clear Browser HSTS Cache

If your browser previously connected to `indi-allsky` over HTTPS, it may retain the HSTS policy in local cache and refuse unencrypted connections:
* In Chromium-based browsers, navigate to `chrome://net-internals/#hsts` and delete the domain from the query list.
* In Firefox, clear site cookies and cache for the host domain.