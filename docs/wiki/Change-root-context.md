# Overview
By default indi-allsky runs with a default context of `/indi-allsky/` for all requests.  It is possible to change the context root with the following config.


## Python view code
Change the blueprint `url_prefix` in the following files
* `indi_allsky/flask/views.py`
* `indi_allsky/flask/auth_views.py`
* `indi_allsky/flask/syncapi_views.py`
* `indi_allsky/flask/actionapi_views.py`

```
bp_allsky = Blueprint(
    'indi_allsky',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/',   # <-- HERE
    #url_prefix='/indi-allsky',
    static_url_path='static',
)
```

## Web server
### Apache
* `/etc/apache2/sites-enabled/indi-allsky.conf`

Change all instances with `/indi-allsky/`.
* Remove the `RewriteRule` rule
* Change `ProxyPass` directives (multiple places in line)
* Change `ProxyPassReverse` directives (multiple places in line)
* Change `Alias` directives

### nginx
* `/etc/nginx/sites-enabled/indi-allsky.conf`

Change all instances with `/indi-allsky`
* Remove `rewrite` rule
* Change `location` directives