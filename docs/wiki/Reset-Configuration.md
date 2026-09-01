# Overview
Use these instructions if you want to revert all configurations to the defaults.

1. Stop indi-allsky

       systemctl --user stop indi-allsky
       systemctl --user stop gunicorn-indi-allsky

1. Activate the virtualenv

       source virtualenv/indi-allsky/bin/activate

1. Backup current config

       ./config.py dump > indi_allsky_config_$(date +%Y%m%d_%H%M%S).json

1. Flush all configs

       ./config.py flush

1. Bootstrap a fresh config

       ./config.py bootstrap

1. Restart the gunicorn service

       systemctl --user restart gunicorn-indi-allsky