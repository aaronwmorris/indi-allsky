import copy
from http.server import BaseHTTPRequestHandler
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from misc import web_recovery as web


class WebRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = Mock()
        self.stack.unit = 'gunicorn-indi-allsky'
        self.stack.active.return_value = ('instance', '/socket')
        self.stack.backend.return_value = 'failure'
        self.stack.proxy.return_value = 'failure'
        self.history = {}
        self.saved = {}

    def run_check(self, time):
        web.check(self.stack, self.history, time, lambda history: self.saved.update(copy.deepcopy(history)))

    def test_only_repeated_backend_failures_restart_and_budget_precedes_request(self):
        self.stack.restart.side_effect = lambda: self.assertEqual(self.saved['restarts'], [120])
        self.run_check(0)
        self.run_check(60)
        self.stack.restart.assert_not_called()
        self.run_check(120)
        self.stack.restart.assert_called_once_with()
        self.stack.restart.side_effect = None
        for t in range(180, 1020, 60):
            self.run_check(t)
        self.assertEqual(self.stack.restart.call_count, 1)
        self.run_check(1020)
        self.assertEqual(self.stack.restart.call_count, 2)
        for t in range(1080, 3720, 60):
            self.run_check(t)
        self.assertEqual(self.stack.restart.call_count, 2)
        self.run_check(3720)
        self.assertEqual(self.stack.restart.call_count, 3)

    def test_healthy_or_misconfigured_backend_and_proxy_only_fault_never_restart(self):
        for backend, proxy in [('healthy', 'failure'), ('mismatch', 'failure'), ('failure', 'healthy')]:
            self.stack.backend.return_value, self.stack.proxy.return_value = backend, proxy
            for t in (0, 60, 120):
                self.run_check(t)
        self.stack.restart.assert_not_called()

    def test_clean_stop_does_not_even_open_activation_socket(self):
        self.stack.active.return_value = None
        self.run_check(1000)
        self.stack.backend.assert_not_called()
        self.stack.proxy.assert_not_called()
        self.stack.restart.assert_not_called()

    def test_stop_between_checks_suppresses_restart(self):
        self.run_check(0)
        self.run_check(60)
        self.stack.active.side_effect = [('a', '/socket'), ('a', '/socket'), None]
        self.history['instance'] = 'a'
        self.run_check(120)
        self.stack.restart.assert_not_called()

    def test_intermittent_failure_and_replacement_reset_streak(self):
        self.run_check(0)
        self.run_check(60)
        self.stack.active.return_value = ('replacement', '/socket')
        self.run_check(120)
        self.stack.backend.return_value = 'healthy'
        self.run_check(180)
        self.stack.backend.return_value = 'failure'
        self.run_check(240)
        self.run_check(300)
        self.stack.restart.assert_not_called()

    def test_running_systemd_socket_is_a_supported_state(self):
        real = web.WebStack('gunicorn', 443)
        real.ctl = Mock(return_value=(
            'Id=gunicorn.service\nActiveState=active\nSubState=running\nJob=\nInvocationID=instance\n\n'
            'Listen=/var/lib/indi-allsky/gunicorn.sock (Stream)\nId=gunicorn.socket\n'
            'ActiveState=active\nSubState=running\nJob=\nInvocationID=socket\n'))
        self.assertEqual(real.active(), ('instance', '/var/lib/indi-allsky/gunicorn.sock'))
        real.ctl.return_value = real.ctl.return_value.replace('Job=\n', 'Job=42\n', 1)
        self.assertIsNone(real.active())

    def test_real_unix_http_and_wrong_responses(self):
        class Reply(BaseHTTPRequestHandler):
            def do_GET(self):
                status = self.server.status
                self.send_response(status)
                self.end_headers()
                self.wfile.write(self.server.payload)

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            sock = str(Path(temp) / 'web.sock')
            with socketserver.UnixStreamServer(sock, Reply) as server:
                for status, body, expected in [(200, web.MARKER, 'healthy'), (200, b'login', 'mismatch'),
                                               (404, b'not found', 'mismatch'), (503, b'out', 'failure')]:
                    server.status, server.payload = status, body
                    thread = threading.Thread(target=server.handle_request)
                    thread.start()
                    try:
                        self.assertEqual(web.probe(web.UnixHTTPConnection(sock)), expected)
                    finally:
                        thread.join(timeout=2)
            self.assertEqual(web.probe(web.UnixHTTPConnection(sock)), 'failure')


if __name__ == '__main__':
    unittest.main()
