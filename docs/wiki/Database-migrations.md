# General

If you update indi-allsky, it may be necessary to upgrade the sqlite database schema.  The python library [Alembic](https://alembic.sqlalchemy.org/) is used to manage the database models in code.

1. Activate python virtual environment

        source virtualenv/indi-allsky/bin/activate

1. [Backup](#backups) the database
1. Run the database migration.

        flask db revision --autogenerate
        flask db upgrade head


# Backups
The sqlite database is located at `/var/lib/indi-allsky/indi-allsky.sqlite`

`.backup` backups can only be restored on the same type of CPU platform

        DB_BACKUP="/var/lib/indi-allsky/backup_$(date +%Y%m%d_%H%M%S).sqlite"
        sqlite3 "/var/lib/indi-allsky/indi-allsky.sqlite" ".backup $DB_BACKUP"
        gzip "$DB_BACKUP"

## Cross-platform backup

        sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite .dump | gzip -c > /var/lib/indi-allsky/backup_$(date +%Y%m%d_%H%M%S).sql.gz


# Restore

1. Move the original DB

        mv /var/lib/indi-allsky/indi-allsky.sqlite /var/lib/indi-allsky/indi-allsky.sqlite_$(date +%Y%m%d_%H%M%S)

1. Restore a `.backup`

        gunzip -c /var/lib/indi-allsky/backup_20211231_010101.sqlite.gz > /var/lib/indi-allsky/indi-allsky.sqlite

    * Restore a `.dump`

            gunzip -c /var/lib/indi-allsky/backup_20211231_010101.sql.gz | sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite


# Fixing broken migrations
If your database has gotten out of sync with the database migrations, use this method to get things in sync.

Errors like: `can't locate revision xxxxxxxxxxxx exited abnormally`

or `ERROR [flask_migrate] Error: Could not determine revision id from filename xxxxxxxxxxxxxx.py`
```
sqlite3 /var/lib/indi-allsky/indi-allsky.sqlite "DELETE FROM alembic_version;"

# from the indi-allsky folder
rm /var/lib/indi-allsky/migrations/versions/*.py

# now rerun setup.sh
```

## Rebuilding database
If you need to rebuild the database, use the following method.
```
rm /var/lib/indi-allsky/indi-allsky.sqlite

# from the indi-allsky folder
rm /var/lib/indi-allsky/migrations/versions/*.py

# now rerun setup.sh
```