#!/usr/bin/env python3
"""Check the local web stack without starting a deliberately stopped service."""
import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import time


PATH = '/indi-allsky/healthz'
MARKER = b'indi-allsky-web-ok\n'
TIMEOUT = 4
FAILURES = 3
COOLDOWN = 900
WINDOW = 3600
MAX_RESTARTS = 2


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=TIMEOUT)
        self.path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(TIMEOUT)
            sock.connect(self.path)
        except BaseException:
            sock.close()
            raise
        self.sock = sock


def probe(connection):
    """Return healthy, failure, or mismatch (wrong URL/vhost/version)."""
    try:
        connection.request('GET', PATH, headers={'Connection': 'close'})
        response = connection.getresponse()
        if response.status == 200 and response.read(len(MARKER) + 1) == MARKER:
            return 'healthy'
        return 'failure' if response.status >= 500 else 'mismatch'
    except (OSError, http.client.HTTPException):
        return 'failure'
    finally:
        connection.close()


class WebStack:
    def __init__(self, unit, port):
        self.unit = unit
        self.port = port

    def ctl(self, *args):
        return subprocess.run(['systemctl', '--user', *args], check=True, timeout=6,
                              text=True, stdout=subprocess.PIPE).stdout

    def active(self):
        # A socket probe on its own could wake a stopped service. Only check
        # a fully running instance and compare its ID again before recovery.
        output = self.ctl('show', self.unit + '.service', self.unit + '.socket',
                          '-p', 'Id', '-p', 'ActiveState', '-p', 'SubState',
                          '-p', 'InvocationID', '-p', 'Listen', '-p', 'Job')
        units = {}
        for block in output.strip().split('\n\n'):
            props = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if props.get('Id'):
                units[props['Id']] = props
        service = units.get(self.unit + '.service', {})
        listener = units.get(self.unit + '.socket', {})
        if (service.get('ActiveState') != 'active' or service.get('SubState') != 'running'
                or listener.get('ActiveState') != 'active' or listener.get('SubState') not in ('running', 'listening')
                or service.get('Job') or listener.get('Job') or not service.get('InvocationID')):
            return None
        path = listener.get('Listen', '')
        if not path.startswith('/') or not path.endswith(' (Stream)'):
            raise ValueError('Expected one filesystem stream socket for ' + self.unit)
        return service['InvocationID'], path[:-len(' (Stream)')]

    def backend(self, path):
        return probe(UnixHTTPConnection(path))

    def proxy(self):
        # A local camera typically uses a self-signed certificate. This request
        # contains no credentials and its connection is restricted to loopback.
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        tls.check_hostname = False
        tls.verify_mode = ssl.CERT_NONE
        return probe(http.client.HTTPSConnection('127.0.0.1', self.port, timeout=TIMEOUT, context=tls))

    def restart(self):
        self.ctl('--no-block', 'try-restart', self.unit + '.service')


def check(stack, history, now, save):
    restarts = [stamp for stamp in history.get('restarts', []) if 0 <= now - stamp < WINDOW]
    history['restarts'] = restarts
    active = stack.active()
    if not active:
        history.pop('instance', None)
        history['failures'] = 0
        history.pop('observation', None)
        save(history)
        return

    instance, path = active
    backend = stack.backend(path)
    if stack.active() != active:
        # Capture a new baseline after worker replacement or maintenance.
        history['failures'] = 0
        save(history)
        return
    proxy = stack.proxy()
    if history.get('instance') != instance:
        history.update(instance=instance, failures=0)
    observation = f'Gunicorn={backend}, local HTTPS proxy={proxy}'
    if history.get('observation') != observation:
        print(observation, flush=True)
        history['observation'] = observation

    # A wrong socket/URL or proxy-only fault is diagnostic. Never try to
    # repair Apache (or a healthy backend) by restarting Gunicorn.
    if backend != 'failure' or proxy == 'healthy':
        history['failures'] = 0
    else:
        history['failures'] = min(FAILURES, history.get('failures', 0) + 1)
    save(history)
    if (history['failures'] < FAILURES or len(restarts) >= MAX_RESTARTS
            or (restarts and now - restarts[-1] < COOLDOWN) or stack.active() != active):
        return

    # Commit the budget before issuing even a rejected or interrupted restart.
    restarts.append(now)
    history['failures'] = 0
    save(history)
    print('Repeated backend failures; requesting recovery of ' + stack.unit, flush=True)
    stack.restart()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    directory = Path(os.environ['RUNTIME_DIRECTORY'])
    state = directory / 'web.json'
    history = json.loads(state.read_text()) if state.exists() else {}

    def save(value):
        data = json.dumps(value)
        if state.exists() and state.read_text() == data:
            return
        tmp = state.with_suffix('.tmp')
        tmp.write_text(data)
        tmp.replace(state)

    check(WebStack(args.unit, args.port), history, int(time.monotonic()), save)


if __name__ == '__main__':
    main()
