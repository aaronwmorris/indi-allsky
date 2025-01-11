#!/usr/bin/env python3

# This script shows how to connect to a WPA protected WiFi network
# by communicating through D-Bus to NetworkManager 0.9.
#
# Reference URLs:
# http://projects.gnome.org/NetworkManager/developers/
# http://projects.gnome.org/NetworkManager/developers/settings-spec-08.html

import sys
import getpass
import dbus
import time
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class ConnectAp(object):
    def main(self):
        ssid = input('Enter the desired SSID: ')
        psk = getpass.getpass('PSK (not echoed): ')

        bus = dbus.SystemBus()
        # Obtain handles to manager objects.
        manager_bus_object = bus.get_object("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager")
        manager = dbus.Interface(manager_bus_object, "org.freedesktop.NetworkManager")
        manager_props = dbus.Interface(manager_bus_object, "org.freedesktop.DBus.Properties")

        # Enable Wireless. If Wireless is already enabled, this does nothing.
        was_wifi_enabled = manager_props.Get("org.freedesktop.NetworkManager", "WirelessEnabled")
        if not was_wifi_enabled:
            logger.info("Enabling WiFi and sleeping for 10 seconds ...")
            manager_props.Set("org.freedesktop.NetworkManager", "WirelessEnabled", True)
            # Give the WiFi adapter some time to scan for APs. This is absolutely
            # the wrong way to do it, and the program should listen for
            # AccessPointAdded() signals, but it will do.
            time.sleep(10)

        # Get path to the 'wlan0' device. If you're uncertain whether your WiFi
        # device is wlan0 or something else, you may utilize manager.GetDevices()
        # method to obtain a list of all devices, and then iterate over these
        # devices to check if DeviceType property equals NM_DEVICE_TYPE_WIFI (2).
        device_path = manager.GetDeviceByIpIface("wlan0")
        logger.info("wlan0 path: %s", device_path)

        # Connect to the device's Wireless interface and obtain list of access
        # points.
        device = dbus.Interface(
            bus.get_object("org.freedesktop.NetworkManager", device_path),
            "org.freedesktop.NetworkManager.Device.Wireless"
        )

        accesspoints_paths_list = device.GetAccessPoints()

        # Identify our access point. We do this by comparing our desired SSID
        # to the SSID reported by the AP.
        our_ap_path = None
        for ap_path in accesspoints_paths_list:
            ap_props = dbus.Interface(
                bus.get_object("org.freedesktop.NetworkManager", ap_path),
                "org.freedesktop.DBus.Properties"
            )

            ap_ssid = ap_props.Get("org.freedesktop.NetworkManager.AccessPoint", "Ssid")

            # Returned SSID is a list of ASCII values. Let's convert it to a proper
            # string.
            str_ap_ssid = "".join(chr(i) for i in ap_ssid)
            logger.info("%s: SSID = %s", ap_path, str_ap_ssid)
            if str_ap_ssid == ssid:
                our_ap_path = ap_path
                break

        if not our_ap_path:
            logger.error("AP not found :(")
            sys.exit(2)

        logger.info("Our AP: %s", our_ap_path)

        # At this point we have all the data we need. Let's prepare our connection
        # parameters so that we can tell the NetworkManager what is the passphrase.
        # https://networkmanager.dev/docs/api/latest/settings-802-11-wireless.html
        connection_params = {
            "802-11-wireless": {
                "security": "802-11-wireless-security",
                "powersave": 2,  # disable power saving
            },
            "802-11-wireless-security": {
                "key-mgmt": "wpa-psk",
                "psk": psk,
            },
        }

        # Establish the connection.
        settings_path, connection_path = manager.AddAndActivateConnection(connection_params, device_path, our_ap_path)
        logger.info("settings_path = %s", settings_path)
        logger.info("connection_path = %s", connection_path)

        # Wait until connection is established. This may take a few seconds.
        NM_ACTIVE_CONNECTION_STATE_ACTIVATED = 2
        logger.info("Waiting for connection to reach ")
        logger.info("NM_ACTIVE_CONNECTION_STATE_ACTIVATED state ...")
        connection_props = dbus.Interface(
            bus.get_object("org.freedesktop.NetworkManager", connection_path),
            "org.freedesktop.DBus.Properties"
        )

        state = 0
        while True:
            # Loop forever until desired state is detected.
            #
            # A timeout should be implemented here, otherwise the program will
            # get stuck if connection fails.
            #
            # IF PASSWORD IS BAD, NETWORK MANAGER WILL DISPLAY A QUERY DIALOG!
            # This is something that should be avoided, but I don't know how, yet.
            #
            # Also, if connection is disconnected at this point, the Get()
            # method will raise an org.freedesktop.DBus.Error.UnknownMethod
            # exception. This should also be anticipated.
            try:
                state = connection_props.Get("org.freedesktop.NetworkManager.Connection.Active", "State")
            except dbus.exceptions.DBusException:
                logger.error("The password may not have been correct")
                raise

            if state == NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
                break

            time.sleep(0.001)

        logger.warning("Connection established!")

        # comment this out to remove the connection
        sys.exit()


        #
        # Connection is established. Do whatever is necessary.
        # ...
        #
        logger.info("Sleeping for 5 seconds ...")
        time.sleep(5)
        logger.info("Disconnecting ...")

        # Clean up: disconnect and delete connection settings. If program crashes
        # before this point is reached then connection settings will be stored
        # forever.
        # Some pre-init cleanup feature should be devised to deal with this problem,
        # but this is an issue for another topic.
        manager.DeactivateConnection(connection_path)

        settings = dbus.Interface(
            bus.get_object("org.freedesktop.NetworkManager", settings_path),
            "org.freedesktop.NetworkManager.Settings.Connection")

        settings.Delete()

        # Disable Wireless (optional step)
        if not was_wifi_enabled:
            manager_props.Set("org.freedesktop.NetworkManager", "WirelessEnabled", False)

        logger.info("DONE!")
        sys.exit()


if __name__ == "__main__":
    ConnectAp().main()


