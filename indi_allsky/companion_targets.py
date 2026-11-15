"""Offline target lookup and projection for the astrophotography companion."""
import csv
import json
import math
from functools import lru_cache
from pathlib import Path
import re
import unicodedata

from ephem.stars import stars


_DIRECTORY = Path(__file__).resolve().parent
# J2000 centres for extended targets outside the NGC/IC catalogue.
# Green (2024), Table I: https://www.mrao.cam.ac.uk/surveys/snrs/snr-catalogue2024-tables.pdf
# Outters (2012), Ou4 discovery: https://outters.fr/wp-content/uploads/2015/12/decouverte-OU4-eu.pdf
_ADDITIONAL_TARGETS = (
    ("Thor's Lightning", 66.75, 55.466667, ("Thor's Lightning Nebula", 'SNR G150.3+4.5')),
    ('Squid Nebula', 317.95075, 59.985833, ('Giant Squid Nebula', 'Tintenfischnebel', 'Ou4', 'Outters 4')),
)
_COMMON_NAMES = {
    'Andromeda': 'M31', 'Andromedagalaxie': 'M31', 'Andromedanebel': 'M31',
    'Orionnebel': 'M42', 'Plejaden': 'M45', 'Pleiades': 'M45',
    'Nordamerikanebel': 'NGC 7000', 'Herznebel': 'IC 1805', 'Seelennebel': 'IC 1848',
    'Krebsnebel': 'M1', 'Ringnebel': 'M57', 'Hantelnebel': 'M27',
    'Polarstern': 'Polaris', 'Wega': 'Vega',
}


def _name_key(name):
    text = unicodedata.normalize('NFKD', name.casefold())
    galactic = re.fullmatch(r'\s*(?:snr\s*)?g\s*(\d+(?:\.\d+)?)\s*([+−-])\s*(\d+(?:\.\d+)?)\s*', text)
    if galactic:
        # The latitude sign distinguishes otherwise different Galactic sources.
        return 'g' + ''.join(galactic.groups()).replace('−', '-')
    key = ''.join(c for c in text if c.isalnum())
    number = re.fullmatch(r'(messier|m|ic|ngc|c)0*([0-9]+)([a-z]*)', key)
    if number:
        prefix, digits, suffix = number.groups()
        return ('m' if prefix == 'messier' else prefix) + digits + suffix
    return key


@lru_cache(maxsize=1)
def _catalog():
    objects = {}
    aliases = {}
    with (_DIRECTORY / 'data/companion_ngc.csv').open(encoding='utf-8', newline='') as source:
        for row in csv.DictReader(source):
            key = _name_key(row['name'])
            objects[key] = (row['name'], float(row['ra_deg']), float(row['dec_deg']))
            for name in row['aliases'].split('|'):
                if name:
                    alias = _name_key(name)
                    if alias in aliases and (aliases[alias] is None or aliases[alias][0] != key):
                        aliases[alias] = None  # several objects share this name
                    else:
                        aliases[alias] = (key, name)
    with (_DIRECTORY / 'flask/static/virtualsky/messier.json').open(encoding='utf-8') as source:
        for row in json.load(source):
            name = row['target']['name']
            objects[_name_key(name)] = (name, row['ra']['decimal'], row['dec']['decimal'])
    for name, star in stars.items():
        objects[_name_key(name)] = (name, math.degrees(star._ra), math.degrees(star._dec))
    for name, ra, dec, names in _ADDITIONAL_TARGETS:
        key = _name_key(name)
        objects[key] = (name, ra, dec)
        for alias in names:
            aliases[_name_key(alias)] = (key, name)
    for name, source in _COMMON_NAMES.items():
        aliases[_name_key(name)] = (_name_key(source), name)
    return objects, aliases


def resolve_name(name):
    if not name or len(name) > 128:
        raise ValueError('Enter an object name or catalogue number.')
    key = _name_key(name)
    objects, aliases = _catalog()
    alias = None
    if key not in objects and key in aliases:
        match = aliases[key]
        if match is None:
            raise ValueError('Several objects share this name. Enter a catalogue number or RA and Dec.')
        key, alias = match
    if key not in objects:
        raise ValueError('Unknown object. Try a Messier, NGC or IC number, a star name, or RA and Dec.')
    label, ra, dec = objects[key]
    return {'label': alias or label, 'ra_deg': ra, 'dec_deg': dec}


_NUMBER = r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)'
_DECIMAL = re.compile(r'([+-]?' + _NUMBER + r')\s*(deg|°|d|h)?')
_SEXAGESIMAL = re.compile(r'([+-]?)([0-9]+)(?::|\s+)([0-9]+)(?:(?::|\s+)(' + _NUMBER + r'))?')
_SYMBOLS = re.compile(r'([+-]?)([0-9]+)\s*([hd°])\s*([0-9]+)\s*[m′\'](?:\s*(' + _NUMBER + r')\s*[s″"])?')


def _angle(raw, is_ra):
    label = 'Right ascension' if is_ra else 'Declination'
    text = (raw or '').strip().lower().replace('−', '-')
    if not text or len(text) > 64:
        raise ValueError('Enter both RA and Dec.')
    decimal = _DECIMAL.fullmatch(text)
    if decimal:
        value = float(decimal[1])
        hours = decimal[2] == 'h'
    else:
        parts = _SEXAGESIMAL.fullmatch(text)
        symbols = _SYMBOLS.fullmatch(text) if not parts else None
        if parts:
            sign, whole, minutes, seconds = parts.groups()
            hours = is_ra
        elif symbols:
            sign, whole, unit, minutes, seconds = symbols.groups()
            hours = unit == 'h'
        else:
            raise ValueError(f'{label} must be in decimal degrees or sexagesimal notation.')
        minutes, seconds = int(minutes), float(seconds or 0)
        if minutes >= 60 or seconds >= 60:
            raise ValueError('Minutes and seconds must each be less than 60.')
        value = int(whole) + minutes / 60 + seconds / 3600
        if sign == '-':
            value = -value
    if hours:
        if not is_ra:
            raise ValueError('Declination is measured in degrees.')
        value *= 15
    if is_ra and not 0 <= value < 360:
        raise ValueError('Right ascension must be 0 to less than 360 degrees (0 to less than 24 hours).')
    if not is_ra and not -90 <= value <= 90:
        raise ValueError('Declination must be between -90 and +90 degrees.')
    return value


def resolve_coordinates(ra, dec):
    ra, dec = _angle(ra, True), _angle(dec, False)
    return {'label': f'{ra:.5f}°, {dec:+.5f}°', 'ra_deg': ra, 'dec_deg': dec}


def marker_coordinates(values):
    if not 1 <= len(values) <= 64:
        raise ValueError('Send between 1 and 64 targets per request.')
    coordinates = []
    for pair in values:
        try:
            ra, dec = map(float, pair.split(','))
        except ValueError:
            raise ValueError('Invalid target coordinates.') from None
        if not 0 <= ra < 360 or not -90 <= dec <= 90:
            raise ValueError('Invalid target coordinates.')
        coordinates.append((ra, dec))
    return coordinates


def project_targets(coordinates, model):
    """Return normalized positions in this archived frame, in input order."""
    if not model or not model.get('location') or model.get('observed_at') is None:
        return None
    width, height = model['image_size']
    lat, lon = model['location']
    if (not width or not height or type(lat) not in (int, float) or not -90 <= lat <= 90
            or type(lon) not in (int, float) or not -180 <= lon <= 180):
        return None
    # Imported only for a frame that carries a verified stellar solution.
    import numpy
    from .aligned_media import projection_values
    from .fisheye import cameraAltAz, projectToPixels
    from .lens_solver.projection import precessCatalog, predictAltAz

    timestamp = model['observed_at']
    values = model['values']
    catalog = numpy.asarray(coordinates, dtype=float)
    if values['PRECESSION']:
        catalog = precessCatalog(catalog, timestamp)
    altitude, azimuth = predictAltAz(catalog, lat + values['LATITUDE_OFFSET'],
                                     lon + values['LONGITUDE_OFFSET'], timestamp)
    params = projection_values(model)
    lens_alt, _ = cameraAltAz(altitude, azimuth, params[7], params[8])
    x, y = projectToPixels(altitude, azimuth, params[:7], width, height,
                           lens_altitude=params[7], pointing_azimuth=params[8])
    return [
        {'x': float(px / width), 'y': float(py / height)}
        if alt > 0 and visible >= 0 and 0 <= px < width and 0 <= py < height else None
        for px, py, alt, visible in zip(x, y, altitude, lens_alt)
    ]
