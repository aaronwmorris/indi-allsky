### astroberry indi-allsky caddy config
        handle /indi-allsky* {
            @static {
                path_regexp \.(jpe?g|png|tiff?|bmp|gif|fits?|webp|jp2|mp4|webm)$
            }

            header @static Cache-Control max-age=5184000

            handle /images/* {
                root * %IMAGE_FOLDER%
                file_server
            }

            handle /static/* {
                root * %ALLSKY_DIRECTORY%/indi_allsky/flask/static
                file_server
            }

            handle {
                reverse_proxy %UPSTREAM_SERVER% 
            }
        }
