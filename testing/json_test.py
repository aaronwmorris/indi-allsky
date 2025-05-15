#!/usr/bin/env python3


import io
import json
import tempfile
from pprint import pprint
from collections import OrderedDict
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class JsonTest(object):

    def __init__(self):
        self.data = OrderedDict({
            'int'   : 2,
            'float' : 1.1,
            'str'   : 'abcd',
            'bool'  : True,
            'special' : '°¡¢£¤¥§©«»®°±¹²³µ™¶¼½¾¿÷ƒΔÀËÏÑÜßãäëñöΩπ∞€',
            'special2' : 'ברי צקלה',
        })

    def main(self):

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as temp_f:
            json.dump(
                self.data,
                temp_f,
                indent=4,
                ensure_ascii=False,
            )

            logger.info('Temp: %s', temp_f.name)


        with io.open(temp_f.name, 'r', encoding='utf-8') as temp_f:
            json_data = json.load(
                temp_f,
                object_pairs_hook=OrderedDict,
            )


        pprint(json_data)

        print()
        print("jq --argjson newfloat 1.2 '.float = $newfloat' {0:s}".format(temp_f.name))


if __name__ == "__main__":
    JsonTest().main()
