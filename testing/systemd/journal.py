#!/usr/bin/env python3

import select
from systemd import journal
import logging


UNIT_NAME = 'indi-allsky.service'



logging.basicConfig(level=logging.INFO)
logger = logging


class JournalReader(object):
    def main(self):
        logger.info('Unit: %s', UNIT_NAME)

        reader = journal.Reader()
        #reader.add_match(_SYSTEMD_UNIT=UNIT_NAME)
        reader.add_match(_SYSTEMD_USER_UNIT=UNIT_NAME)


        #reader.seek_head()

        #for entry in reader:
        #    timestamp = entry.get('__REALTIME_TIMESTAMP')
        #    message = entry.get('MESSAGE', '')

        #    # Only print if there is a message
        #    if message:
        #        print(f"{timestamp} - {message}")


        reader.seek_tail()
        reader.get_previous()  # Fixes edge-case pointer positioning

        poller = select.poll()
        poller.register(reader.fileno(), reader.get_events())

        while True:
            if poller.poll(1000):  # Check every 1 second
                if reader.process() == journal.APPEND:
                    for entry in reader:
                        #for k in entry.keys():
                        #    print('Key: %s', 'Value: %s', k, entry.get(k))

                        #logger.info('User unit: %s', entry.get('_SYSTEMD_USER_UNIT'))
                        #logger.info('System unit: %s', entry.get('_SYSTEMD_UNIT'))

                        timestamp = entry.get('__REALTIME_TIMESTAMP')
                        message = entry.get('MESSAGE', '')
                        print(f"{timestamp} - {message}")



if __name__ == "__main__":
    JournalReader().main()
