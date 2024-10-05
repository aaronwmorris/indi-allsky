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
                timeout=(5.0, 5.0),
            )
        except socket.gaierror as e:
            logger.error('Socket error: %s', str(e))
            self.adsb_aircraft_q.put({})
            return
        except socket.timeout as e:
            logger.error('Socket timeout: %s', str(e))
            self.adsb_aircraft_q.put({})
            return
        except requests.exceptions.ConnectTimeout as e:
            logger.error('Connect timeout: %s', str(e))
            self.adsb_aircraft_q.put({})
            return
        except requests.exceptions.ConnectionError as e:
            logger.error('Connect error: %s', str(e))
            self.adsb_aircraft_q.put({})
            return
        except requests.exceptions.ReadTimeout as e:
            logger.error('Read timeout: %s', str(e))
            self.adsb_aircraft_q.put({})
            return
        except ssl.SSLCertVerificationError as e:
            logger.error('SSL Certificate Validation failed: %s', str(e))
            self.adsb_aircraft_q.put({})
            return
        except requests.exceptions.SSLError as e:
            logger.error('SSL Error: %s', str(e))
            self.adsb_aircraft_q.put({})
            return



        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            self.adsb_aircraft_q.put({})
            return


        try:
            r_data = r.json()
        except json.JSONDecodeError as e:
            logger.error('JSON decode error: %s', str(e))
            self.adsb_aircraft_q.put({})
            return


        aircraft_data = self.adsb_calculate(r_data)


        self.adsb_aircraft_q.put(aircraft_data)


    def adsb_calculate(self, adsb_data):
        alt_min_deg = self.config.get('ADSB', {}).get('MIN_ALT_DEG', 20.0)


        aircraft_list = []

        for aircraft in adsb_data.get('aircraft', []):
            if not aircraft.get('squawk'):
                continue

            if isinstance(aircraft.get('altitude'), str):
                # value might be 'ground' if landed
                continue

            try:
                aircraft_lat = float(aircraft['lat'])
                aircraft_lon = float(aircraft['long'])
                aircraft_altitude = int(aircraft['altitude']) * 0.3048  # convert to meters

                if aircraft.get('flight'):
                    aircraft_id = str(aircraft['flight'])
                else:
                    aircraft_id = str(aircraft['squawk'])
            except KeyError:
                logger.error('Error processing aircraft data')
                continue


            # lets just assume a flat earth... it just makes the math easier  :-)
            distance_deg = math.sqrt((aircraft_lon - self.longitude) ** 2 + (aircraft_lat - self.latitude) ** 2)
            aircraft_distance = distance_deg * 111317  # convert to meters


            # calculate observer info (alt/az astronomy terms)
            aircraft_alt = math.degrees(math.atan((aircraft_altitude - self.elevation) / aircraft_distance))  # offset aircraft altitude by local elevation
            aircraft_az = math.degrees(math.atan2(aircraft_lon - self.longitude, aircraft_lat - self.latitude))


            if aircraft_alt < alt_min_deg:
                logger.warning('Aircraft below minimum visual altitude')
                continue


            logger.info(
                'Aircraft: %s, altitude: %0.1fm, distance: %0.1fm, alt: %0.1f, az: %0.1f',
                aircraft_id,
                aircraft_altitude,
                aircraft_distance,
                aircraft_alt,
                aircraft_az,
            )

            aircraft_list.append({
                'id'        : aircraft_id,
                'alt'       : aircraft_alt,
                'az'        : aircraft_az,
                'altitude'  : aircraft_altitude,  # meters
                'distance'  : aircraft_distance,  # meters
            })


        return aircraft_list

