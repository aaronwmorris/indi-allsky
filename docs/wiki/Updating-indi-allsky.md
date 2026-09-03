# General
indi-allsky upgrades are rolling releases. You should be able to upgrade to the latest release of indi-allsky from any previous release.

---

## Option 1: APT Package Upgrade (Recommended)

If you installed indi-allsky via the official APT repository (`apt.indi-allsky.org`), upgrading is as simple as updating your system packages:

```bash
sudo apt update && sudo apt upgrade -y
```

> [!TIP]
> **Automatic Service Reload & Migrations**:
> Package upgrades automatically update pre-compiled wheels, execute database schema migrations, and reload systemd services without requiring manual intervention.

> [!NOTE]
> All user configuration in `/etc/indi-allsky/flask.json` and databases in `/var/lib/indi-allsky/` are preserved across upgrades.

---

## Option 2: Unattended Upgrade (Source / Git Installs)
indi-allsky now has an unattended upgrade option that can perform a code upgrade with no interaction from the user.

Navigate to `System` -> `Utilities` [tab] and select `Upgrade indi-allsky`.  The upgrade may require up to 5 minutes to complete.  During the upgrade, the indi-allsky capture process will be shutdown and restarted (if it was running) once the upgrade is complete.  A notification will be shown in the web interface once the upgrade has completed.

The unattended upgrade runs as an out-of-band systemd service unit which allows it to function outside the indi-allsky system processes.

* Notes
    * The unattended upgrade will only function when a non-authenticated GitHub checkout has been used (`https://`).
    * The upgrade will only proceed if you are on the `main` branch.
    * Any code modifications prevent the unattended upgrade from running.

### Debugging unattended upgrades
Use the following command to show messages related to the upgrade process

```
journalctl --user-unit=upgrade-indi-allsky
```

### Manual Unattended Upgrade
You may run the unattended upgrade manually if the GitHub checkout requires an SSH key for authentication or you just want to monitor the process.

```
./misc/unattended_upgrade.sh
```

## Normal upgrade
1. Navigate to the current git clone

        cd indi-allsky

1. Stop indi-allsky & gunicorn

        systemctl --user stop indi-allsky

1. Pull the latest changes via git

        git pull origin main

1. Re-run setup.sh to configure system.  _This step is not always required, the indi-allsky service will usually indicate when it is necessary._

        ./setup.sh

     * If you get a message about repositories not being valid, you may have to re-enable NTP time sync

             sudo timedatectl set-ntp true

1. Restart indi-allsky

        systemctl --user start indi-allsky


## Manual upgrade
Note:  This does not upgrade Python modules.  If you have problems with modules, recommend using the setup.sh script.

1. Navigate to the current git clone

        cd indi-allsky

1. Stop indi-allsky & gunicorn

        systemctl --user stop indi-allsky
        systemctl --user stop gunicorn-indi-allsky

1. Pull the latest changes via git

        git pull origin main

1. Upgrade the database schema

        flask db revision --autogenerate
        flask db upgrade head

1. Increment the config version level

        ./config.py edit
        (save the config with no changes)

1. Restart indi-allsky

        systemctl --user start indi-allsky

## Web-only upgrade
1. Navigate to the current git clone

        cd indi-allsky

1. Pull the latest changes via git

        git pull origin main

1. Re-run web_only_setup.sh to configure system

        ./misc/web_only_setup.sh

## Docker upgrade path

https://github.com/aaronwmorris/indi-allsky/wiki/Docker#updating-indi-allsky

# Rename master branch to main
The master branch was renamed to `main` on Feb 17, 2023.  The following commands may be used to rename the branch on your local clone.

    git branch -m master main
    git fetch origin
    git branch -u origin/main main
    git remote set-head origin -a
