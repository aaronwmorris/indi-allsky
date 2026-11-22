#!/usr/bin/env python3


### Alternative
# nmcli -f all c show
# busctl -j call org.freedesktop.NetworkManager /org/freedesktop/NetworkManager/Settings/13 org.freedesktop.NetworkManager.Settings.Connection GetSettings


import dbus
import logging


logging.basicConfig(level=logging.INFO)
logger = logging



class NetworkManagerSettings(object):

    def main(self):
        bus = dbus.SystemBus()


        nm_settings = bus.get_object("org.freedesktop.NetworkManager",
                                     "/org/freedesktop/NetworkManager/Settings")


        settingspath_list = nm_settings.Get("org.freedesktop.NetworkManager.Settings",
                                            "Connections",
                                            dbus_interface=dbus.PROPERTIES_IFACE)


        for settings_path in settingspath_list:
            settings = bus.get_object("org.freedesktop.NetworkManager",
                                      settings_path)


            settings_connection = dbus.Interface(settings,
                                                 "org.freedesktop.NetworkManager.Settings.Connection")

            settings_dict = settings_connection.GetSettings()


            settings_dict = settings_connection.GetSettings()
            logger.info('Settings: %s', settings_dict)


if __name__ == "__main__":
    NetworkManagerSettings().main()

