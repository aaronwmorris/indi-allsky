#!/bin/bash


SHORT_HOSTNAME=$(hostname -s)

openssl req \
    -new \
    -newkey rsa:4096 \
    -sha512 \
    -days 3650 \
    -nodes \
    -x509 \
    -subj "/CN=${SHORT_HOSTNAME}.local" \
    -keyout "ssl.key" \
    -out "ssl.crt" \
    -extensions san \
    -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

