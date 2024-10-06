import math
import socket
import ssl
import json
import requests
import logging

from threading import Thread

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


logger = logging.getLogger('indi_allsky')


class AdsbAircraftHttpWorker(Thread):
    def __init__(
        self,
        idx,
        config,
        adsb_aircraft_q,
        latitude,
        longitude,
        elevation,
    ):
        super(AdsbAircraftHttpWorker, self).__init__()

        self.name = 'AdsbHttp-{0:d}'.format(idx)

        self.config = config
        self.adsb_aircraft_q = adsb_aircraft_q

        self.latitude = latitude
        self.longitude = longitude
        self.elevation = elevation


    def run(self):
        url = self.config.get('ADSB', {}).get('DUMP1090_URL')

        username = self.config.get('ADSB', {}).get('USERNAME')
        password = self.config.get('ADSB', {}).get('PASSWORD')

        cert_bypass = self.config.get('ADSB', {}).get('CERT_BYPASS', True)


        if username:
            basic_auth = requests.auth.HTTPBasicAuth(username, password)
        else:
            basic_auth = None


        if cert_bypass:
            verify = False
        else:
            verify = True


        try:
            r = requests.get(
                url,
                allow_redirects=True,
                verify=verify,
                auth=basic_auth,
                timeout=(4.0, 4.0),
            )
        except socket.gaierror as e:
            logger.error('Socket error: %s', str(e))
            self.adsb_aircraft_q.put([])
            return
        except socket.timeout as e:
            logger.error('Socket timeout: %s', str(e))
            self.adsb_aircraft_q.put([])
            return
        except requests.exceptions.ConnectTimeout as e:
            logger.error('Connect timeout: %s', str(e))
            self.adsb_aircraft_q.put([])
            return
        except requests.exceptions.ConnectionError as e:
            logger.error('Connect error: %s', str(e))
            self.adsb_aircraft_q.put([])
            return
        except requests.exceptions.ReadTimeout as e:
            logger.error('Read timeout: %s', str(e))
            self.adsb_aircraft_q.put([])
            return
        except ssl.SSLCertVerificationError as e:
            logger.error('SSL Certificate Validation failed: %s', str(e))
            self.adsb_aircraft_q.put([])
            return
        except requests.exceptions.SSLError as e:
            logger.error('SSL Error: %s', str(e))
            self.adsb_aircraft_q.put([])
            return



        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            self.adsb_aircraft_q.put([])
            return


        try:
            r_data = r.json()
        except json.JSONDecodeError as e:
            logger.error('JSON decode error: %s', str(e))
            self.adsb_aircraft_q.put([])
            return


        aircraft_data = self.adsb_calculate(r_data)


        self.adsb_aircraft_q.put(aircraft_data)


    def adsb_calculate(self, adsb_data):
        alt_min_deg = self.config.get('ADSB', {}).get('ALT_DEG_MIN', 20.0)


        aircraft_list = []

        for aircraft in adsb_data.get('aircraft', []):
            if isinstance(aircraft.get('altitude'), str):
                # value might be 'ground' if landed
                continue
            elif isinstance(aircraft.get('altitude'), type(None)):
                logger.warning('Aircraft without altitude')
                continue

            try:
                aircraft_lat = float(aircraft['lat'])
                aircraft_lon = float(aircraft['lon'])
                aircraft_altitude_m = int(aircraft['altitude']) * 0.3048  # convert to meters
            except KeyError as e:  # noqa: F841
                #logger.error('KeyError: %s', str(e))
                continue


            aircraft_flight = aircraft.get('flight')
            aircraft_squawk = aircraft.get('squawk')

            if aircraft_flight:
                aircraft_id = str(aircraft_flight).rstrip()
            elif aircraft_squawk:
                aircraft_id = str(aircraft_squawk).rstrip()
            else:
                logger.warning('No aircraft ID')
                continue


            # lets just assume a flat earth... it just makes the math easier  :-)
            distance_deg = math.sqrt((aircraft_lon - self.longitude) ** 2 + (aircraft_lat - self.latitude) ** 2)
            aircraft_distance_m = distance_deg * 111317  # convert to meters


            # calculate observer info (alt/az astronomy terms)
            aircraft_alt = math.degrees(math.atan((aircraft_altitude_m - self.elevation) / aircraft_distance_m))  # offset aircraft altitude by local elevation
            aircraft_az = math.degrees(math.atan2(aircraft_lat - self.latitude, aircraft_lon - self.longitude))  # y first... why?

            if aircraft_az < 0:
                aircraft_az += 360


            if aircraft_distance_m > 50000:
                logger.warning('Aircraft more than 50km away, geographic lat/long may be wrong')


            if aircraft_alt < alt_min_deg:
                logger.info('Aircraft below minimum visual altitude: %0.1f deg', aircraft_alt)
                continue


            #aircraft_distance_nmi = aircraft_distance_m * 0.0005399568
            aircraft_altitude_km = aircraft_altitude_m / 1000
            aircraft_distance_km = aircraft_distance_m / 1000


            logger.info(
                'Aircraft: %s, altitude: %0.1fkm, distance: %0.1fkm, alt: %0.1f, az: %0.1f',
                aircraft_id,
                aircraft_altitude_km,
                aircraft_distance_km,
                aircraft_alt,
                aircraft_az,
            )

            aircraft_list.append({
                'id'        : aircraft_id,
                'flight'    : aircraft_flight,
                'squawk'    : aircraft_squawk,
                'altitude'  : aircraft_altitude_km,
                'distance'  : aircraft_distance_km,
                'alt'       : aircraft_alt,
                'az'        : aircraft_az,
            })


        # sort by closest aircraft
        sorted_aircraft_list = sorted(aircraft_list, key=lambda x: x['distance'])


        return sorted_aircraft_list

