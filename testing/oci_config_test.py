#!/usr/bin/env python3

import oci
#from pprint import pprint


oci_config = oci.config.from_file(file_location='/home/allsky/oci_config.txt')

oci.config.validate_config(oci_config)
