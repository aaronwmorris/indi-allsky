## Install
```
sudo apt-get install mariadb-server
```

## Create database
```
# assuming no password connecting to root from localhost
sudo mysql -u root

CREATE DATABASE indi_allsky
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

## Create user
```
# no ssl
GRANT ALL PRIVILEGES ON indi_allsky.* TO 'indi_allsky_own'@'localhost' IDENTIFIED BY 'password';

# ssl
GRANT ALL PRIVILEGES ON indi_allsky.* TO 'indi_allsky_own'@'%' IDENTIFIED BY 'password' REQUIRE SSL;

FLUSH PRIVILEGES;
```

## Connection strings

File:  `/etc/indi-allsky/flask.json`

### mysqlconnector (recommended)
```
# socket
"SQLALCHEMY_DATABASE_URI": "mysql+mysqlconnector://indi_allsky_own:password@/indi_allsky?charset=utf8mb4&collation=utf8mb4_unicode_ci&unix_socket=/var/run/mysqld/mysqld.sock",

# TCP no ssl
"SQLALCHEMY_DATABASE_URI": "mysql+mysqlconnector://indi_allsky_own:password@localhost:3306/indi_allsky?charset=utf8mb4&collation=utf8mb4_unicode_ci",

# TCP with ssl
"SQLALCHEMY_DATABASE_URI": "mysql+mysqlconnector://indi_allsky_own:password@hostname:3306/indi_allsky?charset=utf8mb4&collation=utf8mb4_unicode_ci&ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_identity",
```

_August 2023: mysql-connector changed the default collation to utf8mb4_0900_ai_ci which is not available in MariaDB.  Update your DB URI to include the new charset and collation._

### PyMySQL
```
# socket
"SQLALCHEMY_DATABASE_URI": "mysql+pymysql://indi_allsky_own:password@/indi_allsky?charset=utf8mb4&unix_socket=/var/run/mysqld/mysqld.sock",

# TCP no ssl
"SQLALCHEMY_DATABASE_URI": "mysql+pymysql://indi_allsky_own:password@localhost:3306/indi_allsky?charset=utf8mb4",

# TCP with ssl
"SQLALCHEMY_DATABASE_URI": "mysql+pymysql://indi_allsky_own:password@hostname:3306/indi_allsky?charset=utf8mb4&ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_identity=false",
```

## DB tuning (optional)
* File: /etc/mysql/mariadb.conf.d/50-server.cnf

```
[mysqld]
...
innodb_file_per_table = 1
lower_case_table_name = 0
innodb_flush_log_at_trx_commit = 0
...
```

## Database setup
* If you have existing configuration in a sqlite database, you can follow these instructions to convert
    * https://github.com/aaronwmorris/indi-allsky/wiki/Database-conversion
* If you want to start from scratch, delete the existing migrations from the sqlite database and ensure the connection URL is updated in `/etc/indi-allsky/flask.json`

        rm -f /var/lib/indi-allsky/migrations/versions/*.py
        
        # indi-allsky git folder
        source virtualenv/indi-allsky/bin/activate

        flask db revision --autogenerate
        flask db upgrade head
        
        ./config.py bootstrap