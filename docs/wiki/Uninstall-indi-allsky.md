If you wish to remove or disable indi-allsky

# Disable services
Running the following commands is sufficient to stop the program from running, but it will remain installed.
```
systemctl --user disable indiserver.service
systemctl --user disable indi-allsky.service
systemctl --user disable indi-allsky.timer
systemctl --user disable gunicorn-indi-allsky.socket
systemctl --user disable gunicorn-indi-allsky.service
```


## Delete services
If you want to permanently delete the services
```
rm -i "$HOME/.config/systemd/user/indiserver.service"
rm -i "$HOME/.config/systemd/user/indi-allksy.service"
rm -i "$HOME/.config/systemd/user/indi-allksy.timer"
rm -i "$HOME/.config/systemd/user/gunicorn-indi-allsky.socket"
rm -i "$HOME/.config/systemd/user/gunicorn-indi-allsky.service"
systemctl --user daemon-reload
```


# Folders
indi-allsky uses the following folders for operation
* `/etc/indi-allsky/` <- configuration (insignificant space usage)
* `/var/log/indi-allsky/` <- logs
* `/var/www/html/allsky/` <- images and videos
* `/var/lib/indi-allsky/` <- database


# Web server
The default install of indi-allsky installs Apache web server


## Disable indi-allsky site config
```
sudo a2dissite indi-allsky
sudo systemctl restart apache2
```


## Delete Apache site
```
sudo rm -i /etc/apache2/sites-available/indi-allsky.conf
sudo rm -i /etc/apache2/sites-enabled/indi-allsky.conf
```


## Disable Apache
```
sudo systemctl disable apache2
```


# Git checkout
Finally, delete the git checkout folder

# TJs AllSky
If you want to switch back to TJ's AllSky, you need to disable the `apache2` service and re-enable the `lighttpd` service.

```
sudo systemctl stop apache2
sudo systemctl disable apache2

sudo systemctl enable lighttpd
sudo systemctl start lighttpd
```