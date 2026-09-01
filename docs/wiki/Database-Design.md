# Overview
indi-allsky's database is implemented via Flask & SQLAlchemy.  indi-allsky is effectively a CLI Flask application.  This permits heavy code reuse between the indi-allsky capture application and the web interface.

https://flask-sqlalchemy.readthedocs.io/

https://www.sqlalchemy.org/


## indi-allsky Database Model
https://github.com/aaronwmorris/indi-allsky/blob/main/indi_allsky/flask/models.py


## SQLAlchemy Object Relational Model
The SQLALchemy ORM is heavily utilized in indi-allsky.  There are no raw SQL commands used to access the database.

https://docs.sqlalchemy.org/en/20/orm/


## Migrations
The Flask-Migrate python module is utilized to manage the database schema.  Flask-Migrate is based on SQLAlchemy and Alembic.  Occasionally, database design updates are made and those are handled as an Alembic database migrations.

https://flask-migrate.readthedocs.io/

https://alembic.sqlalchemy.org/