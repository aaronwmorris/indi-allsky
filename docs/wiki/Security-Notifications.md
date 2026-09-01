# Overview
This page is dedicated to providing notice for security issues that affect indi-allsky.


## Recommended Distributions
The following distributions are recommended if you want to be fully security hardened:
* Debian 13
    * Raspberry Pi OS (trixie)
    * Astroberry 3.0
* Debian 12
    * Raspberry Pi OS (bookworm)
* Ubuntu 24.04
    * Stellarmate OS 1.8.x (beta)
* Ubuntu 22.04
    * Stellarmate OS 1.8.x
* Arch Linux


## Not recommended (but may work)
* Debian 11 (EOL Aug 2026)
    * Raspberry Pi OS (bullseye)
    * As of late 2024, some python modules are dropping support for Python 3.9
* Ubuntu 20.04 (EOL April 2025)
    * Default Python 3.8 EOL October 2024, however indi-allsky uses the included Python 3.9
    * As of late 2024, some python modules are dropping support for Python 3.9


## Unsupported
The following distributions cannot have all Python vulnerabilities fully resolved and should **NOT** be made Internet facing.  Hosting on a home network or behind a firewall should be relatively safe, though.
* Debian 10
    * Raspberry Pi OS (buster)
    * Astroberry Server 2.0
        * _Note: Astroberry 3.0 is based on trixie and is supported_
* Ubuntu 18.04


## Recommended platforms
* x86_64
    * Intel & AMD
* aarch64
    * Raspberry Pi 3+
    * Rockchip
    * Orange Pi 3+
    * Libre Computer


## 32-bit platforms
64-bit platforms have become the de-facto standard today and the Python community appears to be losing interest in supporting 32-bit platforms, especially `armv6l` and `armv7l`.  Many Python module projects are not providing pre-compiled wheels or the modules refuse to build on the platforms.  Sometimes, it is possible to compile the modules from source, but this can take many hours on older, slower SBCs.  In many cases, this forces using older module versions with known security vulnerabilities.  The modules still function as expected, however, it would not be recommended to run any of these systems exposed to the Internet.


### armv6l
armv6l CPUs used in the original Raspberry Pi (v1) and Pi Zero (v1) require special handling.  Many ARM 32-bit Python modules appear to be compiled against the armv7l target which may result in segfaults due to unsupported CPU instructions on armv6l CPUs.  The workaround is installing even older Python modules which do not contain the unsupported instructions.  _These older Python modules will contain security vulnerabilities._


## Python 3.9 (Debian/Raspberry Pi OS 11)
Python 3.9 is end of life as of October 2025.  Python modules necessary for indi-allsky have already stopped supporting this python release and it is necessary to install older module versions.


## Python 3.7 (Debian/Raspberry Pi OS 10)
Python 3.7 is end of life as of June 2023.  Python modules necessary for indi-allsky have already stopped supporting this python release and the functional modules have known security vulnerabilities that cannot be fixed.


### Astroberry 2.0.4
Astroberry 2.0.4 is based on Raspbian 10 and runs Python 3.7.  It is vulnerable to the issues above.


## Python 3.6 (Ubuntu 18)
Ubuntu 18.04 Bionic is end of support as of June 2023.  While extended support is available for the distribution, Python 3.6 is end of life as of December 2021.  The Python modules required for indi-allsky have stopped supporting Python 3.6 in their latest releases and the functional versions have known security vulnerabilities that cannot be fixed.
