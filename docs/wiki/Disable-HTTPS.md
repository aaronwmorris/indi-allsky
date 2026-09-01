# Overview
indi-allsky runs in HTTPS-only mode by default.  Any requests to HTTP are automatically redirect to HTTPS.  You may use the following instructions to disable the HTTPS requirement.

After making these changes, it will be necessary to flush the cache in your browser to remove the HTTP Strict Transport Security [HSTS] settings.

## Disable secure cookies in Flask
* File:  `/etc/indi-allsky/flask.json`

          "SESSION_COOKIE_SECURE": false,
          ...
          "REMEMBER_COOKIE_SECURE": false,

* Restart flask

        systemctl --user restart gunicorn-indi-allsky


## Disable HTTP redirect

### Apache
* File:  `/etc/apache2/sites-enabled/indi-allsky.conf`
* Comment out the `RewriteCond` and `RewriteRule` to prevent the HTTPS redirect

        # HTTP vhost
        <VirtualHost *:80>
            RewriteEngine On
        
            ### Comment this section to permit HTTP access to indi-allsky
            ###  SESSION_COOKIE_SECURE will have to be set to "false" in flash config
            #RewriteCond "%{HTTPS}" off
            #RewriteRule "^/(.*)" "https://%{SERVER_NAME}:443/$1" [R,L]
            ###

* Comment out HSTS config

            ### 1 week HSTS header
            #Header always set Strict-Transport-Security "max-age=604800; includeSubDomains"

* Restart apache

        sudo systemctl restart apache2

### nginx
* File:  `/etc/nginx/sites-enabled/indi-allsky.conf`
* Comment out the `return 302` to prevent the HTTPS redirect

        # HTTP server
        server {
            listen %HTTP_PORT%;
            
            root /var/www/html/allsky;
            
            ### Comment this section to permit HTTP access to indi-allsky
            ###  SESSION_COOKIE_SECURE will have to be set to "false" in flash config
            #return 302 https://$host:%HTTPS_PORT%$request_uri;
            ###

* Comment out HSTS config

            ### 1 week HSTS header
            #add_header Strict-Transport-Security "max-age=604800; includeSubDomains" always;