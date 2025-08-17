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
