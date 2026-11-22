# Purging Pre-Packaged INDI Repositories

When compiling the INDI Library (`libindi`) and third-party driver suites (`indi-3rdparty`) directly from source, pre-existing binary packages installed via Astroberry, Launchpad PPAs, or external repositories must be purged. Failing to remove these packages causes header file discrepancies, library version collisions, and overwritten binaries during standard system updates.

---

## 1. Uninstall Repository Packages

Purge existing INDI packages and remove orphaned runtime dependencies:

```bash
sudo apt-get remove --purge -y \
    indi-full \
    indi-bin \
    libindi-data \
    libindi1 \
    libindi-dev

# Remove orphaned dependencies
sudo apt-get autoremove --purge -y
```

---

## 2. Remove Third-Party Repository Sources

Remove the third-party APT source list configurations:

```bash
# Astroberry repository definitions
sudo rm -f /etc/apt/sources.list.d/astroberry.list

# Jasem Mutlaq INDI PPA repositories (Ubuntu / Debian derivatives)
sudo rm -f /etc/apt/sources.list.d/mutlaqja*.list

# Update package cache
sudo apt-get update
```

---

## 3. Protecting Source-Built INDI from APT Overwrite

Following compilation and installation into `/usr` or `/usr/local`, register the custom build with APT. This informs the package manager that dependencies are satisfied and prevents `apt upgrade` from replacing source-built drivers with older repository binaries:

### Debian Package (`.deb`) and System-wide Deployments
```bash
sudo indi-allsky-ctl protect-source-indi
```

To verify the package hold status at any time:
```bash
sudo indi-allsky-ctl status-indi-hold
```

For comprehensive package management commands, refer to [`indi-allsky-ctl`](indi-allsky-ctl.md).