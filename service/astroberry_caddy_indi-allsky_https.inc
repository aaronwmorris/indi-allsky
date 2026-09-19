### astroberry indi-allsky caddy config
        handle /indi-allsky/images/* {
            root * %IMAGE_FOLDER%
            uri strip_prefix /indi-allsky/images
            file_server
        }

        handle /indi-allsky/static/* {
            root * %ALLSKY_DIRECTORY%/indi_allsky/flask/static
            uri strip_prefix /indi-allsky/static
            file_server
        }

        handle /indi-allsky* {
            reverse_proxy %UPSTREAM_SERVER% 
        }
