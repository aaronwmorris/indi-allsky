worker_class            = 'gthread'
threads                 = 8
timeout                 = 180
syslog                  = True
syslog_addr             = 'unix:///dev/log'
syslog_facility         = 'local7'
loglevel                = 'info'
reload                  = True
reload_engine           = 'inotify'
umask                   = 0o0022

# Not necessary for sockets.  May need to be locked down for a reverse proxy.
forwarded_allow_ips     = '*'


def post_fork(server, worker):
    import logging
    from indi_allsky.otel import init_otel

    init_otel(
        service_name='indi-allsky-web',
        component='gunicorn-worker',
        loggers=[
            logging.getLogger('indi_allsky'),
            logging.getLogger('gunicorn.error'),
        ],
    )
