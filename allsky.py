#!/usr/bin/env python3

import indi_allsky
import logging
import logging.handlers
import argparse


# setup flask context for db access
app = indi_allsky.flask.create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
# logger config in indi_allsky/flask/__init__.py


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() #%(lineno)d: %(message)s')
LOG_FORMATTER_SYSLOG = logging.Formatter('[%(levelname)s] %(processName)s %(module)s.%(funcName)s() #%(lineno)d: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

LOG_HANDLER_SYSLOG = logging.handlers.SysLogHandler(address='/dev/log', facility='local6')
LOG_HANDLER_SYSLOG.setFormatter(LOG_FORMATTER_SYSLOG)



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        choices=(
            'run',
            'darks',
            'flushDarks',
            'generateNightTimelapse',
            'generateDayTimelapse',
            'generateNightKeogram',
            'generateDayKeogram',
            'expireData',
            'dbImportImages',
        ),
    )
    argparser.add_argument(
        '--config',
        '-c',
        help='config file',
        type=argparse.FileType('r'),
        default='/etc/indi-allsky/config.json',
    )
    argparser.add_argument(
        '--timespec',
        '-t',
        help='time spec',
        type=str,
    )
    argparser.add_argument(
        '--cameraId',
        '-C',
        help='camera id (0 == auto)',
        type=int,
        default=0,
    )
    argparser.add_argument(
        '--log',
        '-l',
        help='log output',
        choices=('syslog', 'stderr'),
        default='stderr',
    )
    argparser.add_argument(
        '--server',
        '-s',
        help='indi server',
        type=str,
        default='localhost',
    )
    argparser.add_argument(
        '--port',
        '-p',
        help='indi port',
        type=int,
        default=7624,
    )

    args = argparser.parse_args()


    # log setup
    if args.log == 'syslog':
        logger.addHandler(LOG_HANDLER_SYSLOG)
    elif args.log == 'stderr':
        logger.addHandler(LOG_HANDLER_STREAM)
    else:
        raise Exception('Invalid log output')


    args_list = list()
    kwargs_dict = dict()

    if args.timespec:
        kwargs_dict['timespec'] = (args.timespec)

    if args.cameraId:
        kwargs_dict['camera_id'] = args.cameraId


    ia = indi_allsky.IndiAllSky(args.config)
    ia.indi_server = args.server
    ia.indi_port = args.port

    action_func = getattr(ia, args.action)
    action_func(*args_list, **kwargs_dict)


# vim let=g:syntastic_python_flake8_args='--ignore="E203,E303,E501,E265,E266,E201,E202,W391"'
# vim: set tabstop=4 shiftwidth=4 expandtab
