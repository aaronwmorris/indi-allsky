#!/usr/bin/env python3

#import sys
import io
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from collections import OrderedDict
import socket
import ssl
import requests
from lxml import etree
import shapely
import logging
from pprint import pformat  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging



### ATL
#LATITUDE   = 33.7
#LONGITUDE  = -84.4

### San Francisco
#LATITUDE  = 37.6
#LONGITUDE = -122.4

### NYC
#LATITUDE  = 40.7
#LONGITUDE = -74.0

### Milwaukee
#LATITUDE  = 43.0
#LONGITUDE = -87.9

### Prince Albert
#LATITUDE  = 53.2
#LONGITUDE = -105.8

### WINNIPEG
LATITUDE  = 49.9
LONGITUDE = -97.1

### CALGARY
#LATITUDE  = 51.0
#LONGITUDE = -114.1



class HmsSmokeTest(object):
    # folder name, rating
    hms_kml_folders = OrderedDict({
        # check from light to heavy, in order
        'Smoke (Light)'  : 'Light',
        'Smoke (Medium)' : 'Medium',
        'Smoke (Heavy)'  : 'Heavy',
    })


    # https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/KML/2023/07/hms_smoke20230701.kml
    hms_kml_base_url = 'https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/KML/{now:%Y}/{now:%m}/hms_smoke{now:%Y}{now:%m}{now:%d}.kml'
    kml_temp_file = '/tmp/hms_28727542.kml'


    def __init__(self):
        self.hms_kml_data = None


    def main(self):
        # this polls data from NOAA Hazard Mapping System
        # https://www.ospo.noaa.gov/Products/land/hms.html

        kml_temp_file_p = Path(self.kml_temp_file)

        now = datetime.now()
        #now = datetime.now() - timedelta(days=1)  # testing
        now_minus_3h = now - timedelta(hours=3)


        hms_kml_url = self.hms_kml_base_url.format(**{'now' : now})


        # allow data to be reused
        if not self.hms_kml_data:
            try:
                if not kml_temp_file_p.exists():
                    self.hms_kml_data = self.download_kml(hms_kml_url, kml_temp_file_p)
                elif kml_temp_file_p.stat().st_mtime < now_minus_3h.timestamp():
                    logger.warning('KML is older than 3 hours')
                    self.hms_kml_data = self.download_kml(hms_kml_url, kml_temp_file_p)
                else:
                    self.hms_kml_data = self.load_kml(kml_temp_file_p)
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                self.hms_kml_data = None
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                self.hms_kml_data = None
            except requests.exceptions.ReadTimeout as e:
                logger.error('Timeout error: %s', str(e))
                self.hms_kml_data = None
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                self.hms_kml_data = None
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                self.hms_kml_data = None



        if self.hms_kml_data:
            try:
                xml_root = etree.fromstring(self.hms_kml_data)
            except etree.XMLSyntaxError as e:
                logger.error('Unable to parse XML: %s', str(e))
                raise
            except ValueError as e:
                logger.error('Unable to parse XML: %s', str(e))
                raise

            #location_pt = shapely.Point((float(LONGITUDE), float(LATITUDE)))

            # look for a 1 square degree area (smoke within ~35 miles)
            location_area = shapely.Polygon((
                (float(LONGITUDE) - 0.5, float(LATITUDE) - 0.5),
                (float(LONGITUDE) + 0.5, float(LATITUDE) - 0.5),
                (float(LONGITUDE) + 0.5, float(LATITUDE) + 0.5),
                (float(LONGITUDE) - 0.5, float(LATITUDE) + 0.5),
            ))


            NS = {
                "kml" : "http://www.opengis.net/kml/2.2",
            }


            smoke_rating = 'Clear'  # no matches should mean clear

            found_kml_folders = False
            for folder, rating in self.hms_kml_folders.items():
                p = ".//kml:Folder[contains(., '{0:s}')]".format(folder)
                #logger.info('Folder: %s', p)
                e_folder = xml_root.xpath(p, namespaces=NS)


                if not e_folder:
                    logger.error('Folder not found: %s', folder)
                    continue

                found_kml_folders = True


                for e_placemark in e_folder[0].xpath('.//kml:Placemark', namespaces=NS):
                    for e_polygon in e_placemark.xpath('.//kml:Polygon', namespaces=NS):
                        e_coord = e_polygon.find(".//kml:coordinates", namespaces=NS)
                        #logger.info('   %s', pformat(e_coord.text))

                        coord_list = list()
                        for line in e_coord.text.splitlines():
                            line = line.strip()

                            if not line:
                                continue

                            #logger.info('line: %s', pformat(line))
                            p_long, p_lat, p_z = line.split(',')
                            coord_list.append((float(p_long), float(p_lat)))

                        smoke_polygon = shapely.Polygon(coord_list)

                        #if polygon.contains(location_pt):
                        if location_area.intersects(smoke_polygon):
                            smoke_rating = rating


            if not found_kml_folders:
                # without folders, there was no data to match
                logger.error('No folders in KML')
                smoke_rating = 'No data'


        logger.warning('Smoke rating for %0.1f, %0.1f: %s', LATITUDE, LONGITUDE, smoke_rating)


    def download_kml(self, url, tmpfile):
        logger.warning('Downloading %s', url)
        r = requests.get(url, allow_redirects=True, verify=True, timeout=(15.0, 30.0))

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        with io.open(tmpfile, 'w') as f_kml:
            f_kml.write(r.text)


        return r.text.encode()


    def load_kml(self, tmpfile):
        logger.warning('Loading kml data: %s', tmpfile)
        with io.open(tmpfile, 'rb') as f_kml:
            kml_data = f_kml.read()


        return kml_data


if __name__ == "__main__":
    a = HmsSmokeTest()
    a.main()


