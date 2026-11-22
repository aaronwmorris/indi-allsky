import json
import socket


FIX_MODE_LABELS = {
    0: 'Unknown',
    1: 'No Fix',
    2: '2D Fix',
    3: '3D Fix',
}


def parse_gpsd_messages(messages, host='127.0.0.1', port=2947):
    """Normalize a sequence of decoded gpsd JSON objects into a status dict."""
    tpv = {}
    sky = {}
    devices = []
    version = None

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        msg_class = msg.get('class')
        if msg_class == 'VERSION':
            version = msg.get('release')
        elif msg_class == 'DEVICES':
            devices = msg.get('devices', []) or []
        elif msg_class == 'TPV':
            tpv = msg
        elif msg_class == 'SKY':
            sky = msg
        elif msg_class == 'POLL':
            tpv_list = msg.get('tpv') or []
            sky_list = msg.get('sky') or []
            if tpv_list:
                tpv = tpv_list[-1]
            if sky_list:
                sky = sky_list[-1]

    mode = int(tpv.get('mode', 0) or 0)
    alt = tpv.get('altMSL')
    if alt is None:
        alt = tpv.get('altHAE')
    if alt is None:
        alt = tpv.get('alt')

    raw_sats = sky.get('satellites') or []
    satellites = []
    for sat in raw_sats:
        if not isinstance(sat, dict):
            continue
        satellites.append({
            'PRN': sat.get('PRN'),
            'gnssid': sat.get('gnssid'),
            'svid': sat.get('svid'),
            'el': sat.get('el'),
            'az': sat.get('az'),
            'ss': sat.get('ss'),
            'used': bool(sat.get('used', False)),
        })

    satellites.sort(
        key=lambda s: (
            not s['used'],
            -(s['ss'] if isinstance(s['ss'], (int, float)) else -1),
            s['PRN'] if isinstance(s['PRN'], int) else 9999,
        )
    )

    satellites_used = sum(1 for s in satellites if s['used'])
    if not satellites and 'uSat' in sky:
        satellites_used = int(sky.get('uSat') or 0)
    satellites_visible = len(satellites) if satellites else int(sky.get('nSat') or 0)

    return {
        'connected': True,
        'error': None,
        'host': host,
        'port': port,
        'version': version,
        'devices': [
            {
                'path': d.get('path'),
                'driver': d.get('driver'),
                'bps': d.get('bps'),
                'activated': d.get('activated'),
            }
            for d in devices
            if isinstance(d, dict)
        ],
        'fix': {
            'mode': mode,
            'mode_label': FIX_MODE_LABELS.get(mode, 'Unknown'),
            'time': tpv.get('time'),
            'lat': tpv.get('lat'),
            'lon': tpv.get('lon'),
            'alt': alt,
            'speed': tpv.get('speed'),
            'track': tpv.get('track'),
            'climb': tpv.get('climb'),
            'epx': tpv.get('epx'),
            'epy': tpv.get('epy'),
            'epv': tpv.get('epv'),
            'ept': tpv.get('ept'),
        },
        'sky': {
            'xdop': sky.get('xdop'),
            'ydop': sky.get('ydop'),
            'vdop': sky.get('vdop'),
            'hdop': sky.get('hdop'),
            'pdop': sky.get('pdop'),
            'tdop': sky.get('tdop'),
            'gdop': sky.get('gdop'),
            'satellites_visible': satellites_visible,
            'satellites_used': satellites_used,
            'satellites': satellites,
        },
    }


def query_gpsd(host='127.0.0.1', port=2947, timeout=2.0):
    """Query a running gpsd daemon over TCP and return normalized GPS status."""
    messages = []
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b'?WATCH={"enable":true,"json":true};\n?POLL;\n')

            buf = b''
            got_poll = False
            got_tpv = False
            got_sky = False

            while not got_poll and not (got_tpv and got_sky):
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    line_str = line.decode('utf-8', errors='replace').strip()
                    if not line_str:
                        continue
                    try:
                        msg = json.loads(line_str)
                    except ValueError:
                        continue
                    messages.append(msg)
                    msg_class = msg.get('class')
                    if msg_class == 'POLL':
                        got_poll = True
                        break
                    if msg_class == 'TPV':
                        got_tpv = True
                    elif msg_class == 'SKY':
                        got_sky = True

            try:
                sock.sendall(b'?WATCH={"enable":false};\n')
            except OSError:
                pass
    except OSError as e:
        return {
            'connected': False,
            'error': str(e),
            'host': host,
            'port': port,
            'version': None,
            'devices': [],
            'fix': {
                'mode': 0,
                'mode_label': 'Disconnected',
            },
            'sky': {
                'satellites_visible': 0,
                'satellites_used': 0,
                'satellites': [],
            },
        }

    return parse_gpsd_messages(messages, host=host, port=port)
