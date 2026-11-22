# User & Password Management

`indi-allsky` maintains a dedicated user table (`IndiAllSkyDbUserTable`) with passwords securely hashed using the Argon2 algorithm. Initial administrative credentials are created during the installation wizard.

---

## 1. Web Interface User Management

If you have administrative credentials, users can be managed directly in the web dashboard:
* Navigate to **System** → **Users** (`https://<allsky-host>/indi-allsky/users`).
* Administrators can create new accounts, modify full names and emails, toggle administrator privileges, reset passwords, or deactivate accounts.

---

## 2. Command-Line Management (Debian `.deb` Installations)

On systems installed via official `.deb` packages, user management is handled through [`indi-allsky-ctl`](indi-allsky-ctl) without activating virtual environments:

### List All Accounts
```bash
indi-allsky-ctl user-list
```

### Reset a Password
```bash
sudo indi-allsky-ctl passwd -u <username>
```

### Add a New User
```bash
# Add standard user
sudo indi-allsky-ctl user-add -u <username> -p <password> -n "Display Name" -e "user@example.com"

# Add administrator user
sudo indi-allsky-ctl user-add -u <username> -p <password> -n "Display Name" -e "user@example.com" --admin
```

### Delete a User
```bash
sudo indi-allsky-ctl user-del -u <username>
```

---

## 3. Command-Line Management (Source / Git / `setup.sh` Installations)

For source installations, activate the Python virtual environment and run `misc/usertool.py`:

```bash
# Activate virtual environment
source /var/lib/indi-allsky/virtualenv/bin/activate
# Or from git root: source virtualenv/indi-allsky/bin/activate
```

### List Accounts
```bash
python ./misc/usertool.py list
```

### Reset Password
```bash
python ./misc/usertool.py resetpass -u <username>
```

### Add a New Account
```bash
python ./misc/usertool.py adduser -u <username>
```

### Grant Administrator Rights
```bash
python ./misc/usertool.py setadmin -u <username>
```

### Lock / Deactivate an Account
```bash
python ./misc/usertool.py setinactive -u <username>
```

### Delete an Account
```bash
python ./misc/usertool.py deleteuser -u <username>
```

---

## 4. Authentication Configuration Settings

Global authentication flags reside in `/etc/indi-allsky/flask.json`:

* `LOCAL_AUTH_ENABLE`: Set to `false` if local username/password forms should be disabled in favor of strict OIDC Single Sign-On.
* `INDI_ALLSKY_AUTH_ALL_VIEWS`: Set to `true` to require authentication for all pages, including the public live camera dashboard.
* `INDI_ALLSKY_AUTH_MEDIA_VIEWS`: Set to `true` to require authentication before serving images, timelapses, or keograms.
* `LOGIN_DISABLED`: Setting this to `true` completely disables authentication (use only on isolated offline test benches).