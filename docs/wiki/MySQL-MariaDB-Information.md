# MySQL & MariaDB Configuration

While SQLite is the default database for `indi-allsky`, MySQL or MariaDB may be utilized for multi-camera deployments, network-attached clusters, or dedicated remote web portal servers.

---

## 1. Installation

Install MariaDB server on Debian, Ubuntu, or Raspberry Pi OS:

```bash
sudo apt-get install -y mariadb-server
```

---

## 2. Database & User Provisioning

Connect to the MariaDB CLI as root:
```bash
sudo mysql -u root
```

Create the dedicated `indi_allsky` database with full UTF-8 Unicode character support:
```sql
CREATE DATABASE indi_allsky
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

Create the service user and grant privileges:
```sql
-- For local Unix socket or localhost connections
GRANT ALL PRIVILEGES ON indi_allsky.* TO 'indi_allsky_own'@'localhost' IDENTIFIED BY 'your_password';

-- For remote TCP connections requiring SSL
GRANT ALL PRIVILEGES ON indi_allsky.* TO 'indi_allsky_own'@'%' IDENTIFIED BY 'your_password' REQUIRE SSL;

FLUSH PRIVILEGES;
EXIT;
```

---

## 3. Connection Strings (`flask.json`)

Configure `SQLALCHEMY_DATABASE_URI` in `/etc/indi-allsky/flask.json`:

### Local Unix Domain Socket (Recommended for Local MariaDB)
```json
"SQLALCHEMY_DATABASE_URI": "mysql+mysqlconnector://indi_allsky_own:your_password@/indi_allsky?charset=utf8mb4&collation=utf8mb4_unicode_ci&unix_socket=/var/run/mysqld/mysqld.sock"
```

### Localhost TCP
```json
"SQLALCHEMY_DATABASE_URI": "mysql+mysqlconnector://indi_allsky_own:your_password@localhost:3306/indi_allsky?charset=utf8mb4&collation=utf8mb4_unicode_ci"
```

### Remote Host with SSL
```json
"SQLALCHEMY_DATABASE_URI": "mysql+mysqlconnector://indi_allsky_own:your_password@db.example.com:3306/indi_allsky?charset=utf8mb4&collation=utf8mb4_unicode_ci&ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_identity"
```

> [!NOTE]
> MariaDB uses `utf8mb4_unicode_ci`. Specifying both `charset=utf8mb4` and `collation=utf8mb4_unicode_ci` ensures compatibility across modern versions of `mysql-connector-python`.

---

## 4. Server Engine Tuning

For performance optimization under high frame rates, edit `/etc/mysql/mariadb.conf.d/50-server.cnf`:

```ini
[mysqld]
innodb_file_per_table = 1
innodb_flush_log_at_trx_commit = 2
innodb_buffer_pool_size = 512M
tmpdir = /var/tmp
```
Restart MariaDB:
```bash
sudo systemctl restart mariadb
```

---

## 5. Converting Existing SQLite Data

To migrate existing media history and camera parameters from SQLite into MariaDB, follow the [Database Conversion](Database-conversion) guide.