import urllib.request
import urllib.error
import base64
import json
import os

def send_allsky_map_ping(config, logger, db_notification_helper=None):
    """
    Sends the Allsky Map status ping.
    Returns: (bool, str) - (Success Status, Message/Error description)
    """
    allskymap_conf = config.get('ALLSKYMAP', {})
    api_url = allskymap_conf.get('API_URL')
    api_key = allskymap_conf.get('API_KEY')

    if not api_url or not api_key:
        return False, "API URL or API Key is missing."

    # Format the URL
    api_url = api_url.rstrip('/')
    if not api_url.endswith('/api/ping'):
        api_url = f"{api_url}/api/ping"

    # Lat/Lng
    lat = config.get('LOCATION_LATITUDE', 0.0)
    lng = config.get('LOCATION_LONGITUDE', 0.0)

    # Metadata overrides
    name = allskymap_conf.get('CAMERA_NAME')
    if not name:
        name = config.get('CAMERA', {}).get('NAME', 'My Indi-Allsky Camera')
    owner = allskymap_conf.get('CAMERA_OWNER', '')
    site_url = allskymap_conf.get('WEBSITE_URL', '')

    # Image Base64
    image_base64 = ''
    if allskymap_conf.get('UPLOAD_IMAGE', True):
        img_folder = config.get('IMAGE_FOLDER')
        if img_folder:
            img_path = os.path.join(img_folder, 'latest.jpg')
            if os.path.exists(img_path):
                try:
                    with open(img_path, 'rb') as f:
                        img_data = f.read()
                    if len(img_data) <= 5 * 1024 * 1024:
                        image_base64 = base64.b64encode(img_data).decode('utf-8')
                    else:
                        if logger:
                            logger.warning('Allsky Map Ping: latest.jpg is larger than 5MB limit')
                except Exception as e:
                    if logger:
                        logger.error('Allsky Map Ping failed to read image file: %s', e)

    payload = {
        "name": name,
        "owner": owner,
        "lat": float(lat) if lat else 0.0,
        "lng": float(lng) if lng else 0.0,
        "siteUrl": site_url,
        "imageBase64": image_base64,
    }

    data = json.dumps(payload).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': api_key,
    }

    req = urllib.request.Request(api_url, data=data, headers=headers, method='POST')

    try:
        # Shorter timeout for views (5s) vs daemon tasks (15s)
        timeout = 5 if db_notification_helper is None else 15
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_body = response.read().decode('utf-8')
            if logger:
                logger.info('Allsky Map Ping successful: %s', res_body)
            return True, f"Success! {res_body}"
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='replace')
        if logger:
            logger.error('Allsky Map Ping HTTP Error %d: %s', e.code, err_msg)
        
        # If running in daemon mode, add system notification warning
        if db_notification_helper and e.code in (401, 403):
            try:
                from .flask.models import NotificationCategory
                from datetime import timedelta
                db_notification_helper(
                    NotificationCategory.STATE,
                    'allskymap_auth_error',
                    f'Allsky Map API Authentication Error: {err_msg}',
                    expire=timedelta(days=1),
                )
            except Exception:
                pass
        return False, f"HTTP Error {e.code}: {err_msg}"
    except urllib.error.URLError as e:
        if logger:
            logger.warning('Allsky Map Ping Network Warning: %s', e.reason)
        return False, f"Network unreachable: {e.reason}"
    except Exception as e:
        if logger:
            logger.error('Allsky Map Ping Unexpected Error: %s', e)
        return False, f"Unexpected error: {str(e)}"
