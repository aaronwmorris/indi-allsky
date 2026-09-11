# General

Initial credentials for the web interface are created during installation.

---

## Debian Package Installations (`indi-allsky-ctl`)

On systems installed via `.deb` packages, you can manage users directly using [`indi-allsky-ctl`](indi-allsky-ctl) without activating virtualenvs:

### List Users
```bash
indi-allsky-ctl user-list
```

### Change Password
```bash
sudo indi-allsky-ctl passwd -u username
```

### Add a New User
```bash
sudo indi-allsky-ctl user-add -u username -p password -n "Full Name" -e "user@example.com" --admin
```

### Delete a User
```bash
sudo indi-allsky-ctl user-del -u username
```

---

## Legacy Source / `setup.sh` Installations

Running usertool manually requires activating the indi-allsky virtualenv:

```bash
source virtualenv/indi-allsky/bin/activate
```

### List users
```bash
./misc/usertool.py list
```

### Change password
```bash
./misc/usertool.py resetpass -u username
```

### New Users
```bash
./misc/usertool.py adduser -u username
```

### Set user as administrator
```bash
./misc/usertool.py setadmin -u username
```

### Deactivate/lock user
```bash
./misc/usertool.py setinactive -u username
```

### Delete Users
```bash
./misc/usertool.py deleteuser -u username
```