#!/usr/bin/env python3

import dbus
import logging
import pprint


logging.basicConfig(level=logging.INFO)
logger = logging

class ListConns(object):
    def main(self):
        # require access to system bus
        bus = dbus.SystemBus()

        # access network manager (nm)
        nm = bus.get_object("org.freedesktop.NetworkManager",
                            "/org/freedesktop/NetworkManager")

        # get active connections
        connpath_list = nm.Get("org.freedesktop.NetworkManager",
                               "ActiveConnections", dbus_interface=dbus.PROPERTIES_IFACE)

        for connpath in connpath_list:
            conn = bus.get_object("org.freedesktop.NetworkManager", connpath)


            conn_id = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
                                    "Id", dbus_interface=dbus.PROPERTIES_IFACE)


            devices_list = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
                                    "Devices", dbus_interface=dbus.PROPERTIES_IFACE)


            ipv4configpath = conn.Get("org.freedesktop.NetworkManager.Connection.Active",
                                      "Ip4Config", dbus_interface=dbus.PROPERTIES_IFACE)

            ipv4config = bus.get_object(
                "org.freedesktop.NetworkManager", ipv4configpath)


            addressdata = ipv4config.Get("org.freedesktop.NetworkManager.IP4Config",
                                         "AddressData", dbus_interface=dbus.PROPERTIES_IFACE)

            logger.info("Conn: %s", conn_id)
            device_list = list()
            for device in devices_list:
                device_config = bus.get_object(
                    "org.freedesktop.NetworkManager", device)

                device_int = device_config.Get("org.freedesktop.NetworkManager.Device",
                                         "Interface", dbus_interface=dbus.PROPERTIES_IFACE)
                device_list.append(device_int)

            logger.info("Devices: %s", ', '.join(device_list))

            address_list = list()
            for address in addressdata:
                address_str = '{0:s}/{1:d}'.format(address['address'], address['prefix'])
                address_list.append(address_str)

            logger.info("Addresses: %s", ', '.join(address_list))


if __name__ == "__main__":
    ListConns().main()
