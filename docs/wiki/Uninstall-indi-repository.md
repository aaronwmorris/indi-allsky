# General
If you wish to manually compile indi, but you have already installed indi via Astroberry or other repository, you will need to uninstall the repository packages

## Uninstall packages

```
sudo apt-get remove indi-full libindi-data

# cleanup orphaned packages
sudo apt-get autoremove
```

## Remove repo
```
# astroberry
sudo rm -i /etc/apt/sources.list.d/astroberry.list

# indi PPA
sudo rm -i /etc/apt/sources.list.d/mutlaqja*.list
```

## Protecting Source-Built INDI from APT Overwrites
After compiling and installing INDI from source, register your custom build with APT so package dependencies are satisfied and repository updates will not overwrite your compiled drivers:

```bash
sudo indi-allsky-ctl protect-source-indi
```

See [`indi-allsky-ctl`](indi-allsky-ctl) for more driver and package management details.