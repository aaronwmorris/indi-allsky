# Overview
As a general rule, I do not recommend using MySQL/MariaDB instead of Sqlite.  Sqlite actually performs quite well and is faster than MariaDB in almost all use-cases for indi-allsky.  Sqlite will also use less memory.

Certain functions like automated database backups do not work with MariaDB.


# General

Use these instructions to convert your Sqlite database to MariaDB/MySQL.
1. Stop indi-allsky

        systemctl --user stop indi-allsky

1. Activate virtualenv

        source virtualenv/indi-allsky/bin/activate

1. Ensure your database schema is at the latest level

        flask db revision --autogenerate
        flask db upgrade head

1. Create new mysql database
    * https://github.com/aaronwmorris/indi-allsky/wiki/MySQL-MariaDB-Information

1. Update SqlAlchemy URL and migration folder in `/etc/indi-allsky/flask.json`
    * `SQLALCHEMY_DATABASE_URI`
    * `MIGRATION_FOLDER` - set to `/var/lib/indi-allsky/migrations_mysql`

1. Initialize new migrations

        flask db init

1. Create initial revision

        flask db revision --autogenerate

1. Upgrade revision

        flask db upgrade head

1. Update conversion script with the mysql DST_URL
    * `misc/convert_db.py`

1. Run migration script
    * This process can take 3-5 minutes on Raspberry Pi hardware, be patient

1. Restart indi-allsky
