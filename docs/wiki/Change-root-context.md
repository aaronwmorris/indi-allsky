# Modifying the Web Root Context

By default, `indi-allsky` serves its web interface and static assets from the `/indi-allsky/` URL prefix. Requests arriving at the root (`/`) are redirected to `/indi-allsky/`.

Hosting `indi-allsky` at the domain root (`/`) or under a custom subpath can be achieved primarily via reverse proxy configuration without modifying source code.

---

## 1. Caddy Configuration (Recommended)

When using Caddy (the standard reverse proxy deployed with `indi-allsky`), edit `/etc/caddy/Caddyfile` (or `/etc/caddy/conf.d/indi-allsky.conf`):

```caddy
https://your-domain.example.com {
    tls /etc/caddy/ssl/indi-allsky_caddy.pem /etc/caddy/ssl/indi-allsky_caddy.key

    # Static assets and media files
    handle /images/* {
        root * /var/www/html/allsky/images
        file_server
    }

    handle /static/* {
        root * /usr/share/indi-allsky/indi_allsky/flask/static
        file_server
    }

    # Pass root traffic to the Gunicorn WSGI socket/upstream
    handle /* {
        reverse_proxy unix//run/gunicorn-indi-allsky/socket
    }
}
```

Reload Caddy:
```bash
sudo systemctl reload caddy
```

---

## 2. Nginx Configuration

If using Nginx (`/etc/nginx/sites-enabled/indi-allsky.conf`), adjust the location blocks and upstream directives:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.example.com;

    ssl_certificate /etc/ssl/certs/indi-allsky.crt;
    ssl_certificate_key /etc/ssl/private/indi-allsky.key;

    # Static files served directly
    location /images/ {
        alias /var/www/html/allsky/images/;
        expires 1h;
    }

    location /static/ {
        alias /usr/share/indi-allsky/indi_allsky/flask/static/;
        expires 7d;
    }

    # Reverse proxy root traffic to Gunicorn
    location / {
        proxy_pass http://unix:/run/gunicorn-indi-allsky/socket;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Reload Nginx:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 3. Operational Considerations

* **API Endpoints**: External integrations (Home Assistant, Action API, SyncAPI) must update their configured base URLs if the prefix changes.
* **OIDC Redirect URI**: If OpenID Connect authentication is active, update the redirect URI registered with your Identity Provider to match the new root path (`https://your-domain.example.com/oidc/callback`).