# Indi Allsky Docker support

## docker-compose

### Setup
Use the `setup_env.sh` script to setup your .env environment file and ssl certificates

```
./setup_env.sh
```

### Build containers

```
docker-compose build
```

### Run containers
```
docker-compose up --detach
```

### Stop containers
```
docker-compose down
```


## Info

The docker compose setup sets up a single container per process.

### Containers

* indiserver (privileged)
* indi-allsky capture process
* gunicorn python application server
* nginx reverse proxy
* MariaDB database

### Volumes

* images
* migrations (flask)
* database (MariaDB)

