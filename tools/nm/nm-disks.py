#!/usr/bin/env python3


import dbus
import logging


logging.basicConfig(level=logging.INFO)
logger = logging



class DiskSettings(object):

    def main(self):
        bus = dbus.SystemBus()


        nm_udisks2 = bus.get_object(
            "org.freedesktop.UDisks2",
            "/org/freedesktop/UDisks2")

        iface = dbus.Interface(
            nm_udisks2,
            'org.freedesktop.DBus.ObjectManager')


        object_paths = iface.GetManagedObjects()

        for object_path in object_paths:
            logger.info('%s', object_path)

            if not object_path.startswith('/org/freedesktop/UDisks2/drives/'):
                continue

            #logger.info('%s', object_path)

            settings = bus.get_object(
                "org.freedesktop.UDisks2",
                object_path)

            settings_connection = dbus.Interface(
                settings,
                dbus_interface='org.freedesktop.DBus.Properties')

            settings_dict = settings_connection.GetAll('org.freedesktop.UDisks2.Drive')
            #logger.info('Settings: %s', settings_dict)

            #drive_id = settings_connection.Get('org.freedesktop.UDisks2.Drive', 'Id')
            #vendor = settings_connection.Get('org.freedesktop.UDisks2.Drive', 'Vendor')
            #model = settings_connection.Get('org.freedesktop.UDisks2.Drive', 'Model')
            #serial = settings_connection.Get('org.freedesktop.UDisks2.Drive', 'Serial')
            #size = settings_connection.Get('org.freedesktop.UDisks2.Drive', 'Size')
            #canpoweroff = settings_connection.Get('org.freedesktop.UDisks2.Drive', 'CanPowerOff')
            #removable = settings_connection.Get('org.freedesktop.UDisks2.Drive', 'Removable')
            #ejectable = settings_connection.Get('org.freedesktop.UDisks2.Drive', 'Ejectable')

            drive_id = settings_dict['Id']
            vendor = settings_dict['Vendor']
            model = settings_dict['Model']
            serial = settings_dict['Serial']
            size = settings_dict['Size']
            canpoweroff = settings_dict['CanPowerOff']
            removable = settings_dict['Removable']
            ejectable = settings_dict['Ejectable']
            connectionbus = settings_dict['ConnectionBus']

            logger.info(' Id: %s', str(drive_id))
            logger.info(' %s %s %s', str(vendor), str(model), str(serial))
            logger.info(' Size: %s', str(size))
            logger.info(' ConnectionBus: %s', str(connectionbus))
            logger.info(' CanPowerOff: %s', str(canpoweroff))
            logger.info(' Removable: %s', str(removable))
            logger.info(' Ejectable: %s', str(ejectable))


if __name__ == "__main__":
    DiskSettings().main()

