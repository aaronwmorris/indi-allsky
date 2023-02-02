### INCOMPLETE ###

FROM debian:bullseye-slim

ENV DEBIAN_FRONTEND noninteractive

# Dependencies for the client .deb
RUN apt-get update && apt-get install -y \
    lsb-release \
	ca-certificates \
    git \
    sudo


#VOLUME ["/etc/indi-allsky", "/var/lib/indi-allsky", "/var/www/html/allsky"]


RUN useradd -m -s /bin/bash allsky
RUN usermod -a -G sudo allsky

RUN echo "allsky ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/allsky
RUN chmod 0440 /etc/sudoers.d/allsky


USER allsky

WORKDIR /home/allsky
RUN git clone https://github.com/aaronwmorris/indi-allsky.git


WORKDIR /home/allsky/indi-allsky
RUN ./misc/build_indi_noansible.sh



# simulate shell variables
ENV USER=allsky
ENV PGRP=allsky
ENV DBUS_SESSION_BUS_ADDRESS=foobar

RUN ./setup.sh

