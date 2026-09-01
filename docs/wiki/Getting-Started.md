# Overview
indi-allsky has a significant set of library requirements.  Not every package that is installed is needed in all cases, however, they are installed as a precaution.  In some cases where pre-compiled Python wheels are not available for a platform, the Python pip tool may attempt to compile python modules from source.

## Recommendations
| Component             | Recommendation  | Minimum | Note |
| --------------------- | --------------- | ------- | ---- |
| Single board computer | Raspberry Pi 4+<br>Any SBC with 2+GB of RAM | Raspberry Pi 3 | |
| Mini PC               | Any modern Intel/AMD processor<br>Most Virtualization Platforms | | |
| Platform              | 64-bit          | 64-bit  | :x: 32-bit builds will not finish as of April 2026 |
| OS                    | Ubuntu 24.04 Noble or Debian 13 Bookworm | Ubuntu 22.04/Debian 12 | |
| CPUs                  | 2+              | 1       | |
| RAM                   | 2+              | 1       | |
| Storage               | 256GB           | 64GB    | |


### 32-bit builds (x86 & armhf)
:x: As of April 2026, 32-bit builds will not longer complete due to Python module requirements. :x:

Current not working due to having to compile python module `dask-image` which requires `dask[array,dataframe]` which requires `pyarrow`. pyarrow will not compile without Apache Arrow libs (not available on 32-bit platforms)

**WARNING**: Many python modules need to be compiled from source.  This can take several hours to complete.  Recommend the 64-bit release.


## Warning
Due to the large number of packages installed, it is **NOT** recommended to install indi-allsky on a production system that has other purposes.  indi-allsky will not damage your system, but if you uninstall indi-allsky it can be difficult to remove all of the dependencies and you may be left with 3-5GB of additional packages that you do not need.  All of the packages are regular system packages, so they will still be managed and patched through the system package manager (apt).


## Full Install
To run an instance of indi-allsky, you need to perform the following actions:

1. (Optional) Setup locales

       sudo dpkg-reconfigure locales

1. Install git

       sudo apt-get update
       sudo apt-get install git

1. Clone the indi-allsky git repository

      git clone https://github.com/aaronwmorris/indi-allsky.git

    * Note:  If git prompts for a password, use the following command instead.
        
          GIT_ASKPASS=false git clone https://github.com/aaronwmorris/indi-allsky.git

1. Navigate to the indi-allky sub-directory

       cd indi-allsky/

1. Run setup.sh to install the indi-allsky system

       ./setup.sh

    * _The setup.sh script will tell you if you are required to build the INDI software (documented below)_
    * Note 1: If you run into problems with missing commands here, you may need to install additional packages to get started.

          sudo apt-get install lsb-release libc-bin whiptail

          # Ubuntu only
          sudo apt-get install software-properties-common

    * Note 2:  If you run into a problem where the DBUS user session is not found even after rebooting, make sure you are running setup.sh **WITHOUT** the use of a virtual terminal such as `screen`, `tmux`, or `byobu`.  Some condition, which is not fully understood, may cause problems with the DBUS user session.

1. Start the software

       systemctl --user start indi-allsky

    * _Make sure your camera is plugged in before starting the services_

1. Login to the indi-allsky web application https://raspberrypi.local/
   * *Note: The web server is configured with a self-signed certificate.*


## INDI requirements
indi-allsky requires a modern version of the INDI library (2.0.0+) to operate.  This will have to be installed from a custom repository or built from source.  Pre-compiled binaries are currently only available for the Ubuntu x86_64 and arm64 distribution.  The setup.sh script will automatically setup the INDI PPA repository for you under Ubuntu.


### Compiling INDI
indi-allsky includes a script for compiling INDI from source.  The script is completely self-contained and automated.

`./misc/build_indi.sh`

The script requires an Internet connection to download packages and the source from GitHub.

| System             | Time           | Notes |
| ------------------ | -------------- | ----- |
| Modern PC          | 10-20 minutes  |       |
| Raspberry Pi 5     | 10-20 minutes  | Active cooling |
| Raspberry Pi 4 4GB | 40 minutes     | Requires more time if you do not have a fan/heatsink |
| Raspberry Pi 3 1GB | 3-4 hours      |       |

#### libcamera only build
If you plan on using a libcamera supported camera module, you only need to compile the core INDI library (without the 3rd party libraries and drivers).  **This can reduce your compile time by 50%**

**WARNING**: If you do this, the 3rd party indiserver drivers for ZWO, Player One, Touptek, etc will **NOT** be built.


## indiserver-only Install
1. Install git

       sudo apt-get install git

1. Clone the indi-allsky git repository

       git clone https://github.com/aaronwmorris/indi-allsky.git

1. Navigate to the indi-allky sub-directory

       cd indi-allsky/

1. Run indiserver_only_setup.sh to install the indiserver

       ./misc/indiserver_only_setup.sh

    * _The setup script will tell you if you are required to build the INDI software (documented below)_


### Manual operation
1. Stop indi-allsky service

       systemctl --user stop indi-allsky

1. Activate the indi-allsky python virtual environment

       source virtualenv/indi-allsky/bin/activate

1. Start indi-allsky

       ./allsky.py run


## Services
The indi-allsky system consists of three services:

| Service    | systemd              | Purpose |
| ---------- | -------------------- | ------- |
| Capture    | indi-allsky          | Responsible for taking images, generating timelapses, and file transfers |
| indiserver | indiserver           | Manages the camera hardware |
| Web Server | gunicorn-indi-allsky | Web interface |


## Web-only install
The web-only install is intended for configuration to use the [SyncAPI](https://github.com/aaronwmorris/indi-allsky/wiki/SyncAPI-Setup) and no camera is directly connected.

1. Install git

       sudo apt-get install git


2. Clone the indi-allsky git repository

       git clone https://github.com/aaronwmorris/indi-allsky.git


3. Navigate to the indi-allky sub-directory

       cd indi-allsky/


4. Run setup.sh to install the indi-allsky system

       ./misc/web_only_setup.sh


5. Login to the indi-allsky web application
https://hostname/
 * *Note: The web server is configured with a self-signed certificate.*

6. On an internet-facing system, you now have the opportunity to setup proper signed certificate using [Lets Encrypt](https://letsencrypt.org/) or a similar service.  The certificate locations can be updated in the following location:
 * `/etc/apache2/sites-enabled/indi-allsky.conf`