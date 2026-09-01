# General

The initial credentials for the web interface are created during the run of the setup.sh script.

Running usertool requires the indi-allsky virtualenv.

```bash
source virtualenv/indi-allsky/bin/activate
```

## List users
```bash
./misc/usertool.py list
```

## Change password
The web interface password may be changed with the following commands:
```bash
./misc/usertool.py resetpass -u username
```

## New Users
New users may be added with the following commands:
```bash
./misc/usertool.py adduser -u username
```

## Set user as administrator
```bash
./misc/usertool.py setadmin -u username
```

## Deactivate/lock user
```bash
./misc/usertool.py setinactive -u username
```

## Delete Uses
```bash
./misc/usertool.py deleteuser -u username
```