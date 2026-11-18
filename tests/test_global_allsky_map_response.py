"""Response preservation and canonical identity; every HTTP response is synthetic."""
import copy
import io
import json
import unittest
from urllib import error
from unittest.mock import patch
from tests import test_global_allsky_map as fixtures
from indi_allsky import global_allsky_map as G
from indi_allsky.flask import db
from indi_allsky.flask.models import IndiAllSkyDbTaskQueueTable


class MapResponseTest(unittest.TestCase):
    setUp = fixtures.GlobalMapTest.setUp
    tearDown = fixtures.GlobalMapTest.tearDown
    open = fixtures.GlobalMapTest.open
    run_job = fixtures.GlobalMapTest.run_job

    def response(self, body, headers=None):
        response = fixtures.Response(body)
        response.headers = headers or {'Content-Type': 'text/plain; charset=utf-8'}
        return response

    def test_canonical_release_package_development_and_user_agent(self):
        versions = ['indi_v2026.11.11', 'indi_v2026.11.11+debian.development.abcdef01',
                    'indi_v2026.11.11-dev', 'indi_v2026.11.11.dev1', 'indi_v2026.11.11~rc1']
        for version in versions:
            with self.subTest(version=version), patch.object(G, '__version__', version):
                self.assertEqual(G.canonical_version(), 'indi_v2026.11.11')
                data = self.s._payload(self.cfg, True)
                self.assertEqual(data['allsky_version'], 'indi_v2026.11.11')
                db.session.rollback()  # Pure post() must not inherit this fixture's metadata read.
                G.post(data, self.open)
                self.assertEqual(self.calls[-1][0].get_header('User-agent'), 'indi-allsky/indi_v2026.11.11')
                self.assertEqual(G.__version__, version)  # Other application reporting unchanged.
        with self.assertRaises(G.MapError): G.canonical_version('unknown')

    def test_normal_terminal_results_and_only_content_type_retained(self):
        data = self.s._payload(self.cfg, True)
        for body, status, ok in [(b'RETURN INSERTED\r\n', 'INSERTED', True),
                                 (b'RETURN UPDATED 2 5\n', 'UPDATED', True),
                                 (b'RETURN ERROR rejected\n', 'ERROR', False)]:
            records = []
            with self.subTest(status=status):
                result = G.post(data, lambda *a, **k: self.response(body, {
                    'Content-Type': 'text/plain', 'Set-Cookie': 'must-not-store',
                    'Authorization': 'must-not-store'}), record=lambda e: records.append(copy.deepcopy(e)))
                self.assertEqual((result['status'], result['ok']), (status, ok))
                evidence = records[-1]
                self.assertEqual(evidence['http_status'], 200)
                self.assertEqual(evidence['content_type'], 'text/plain')
                self.assertEqual(evidence['body'], body.decode())
                self.assertEqual(evidence['terminal_result']['status'], status)
                self.assertNotIn('must-not-store', json.dumps(records))
                self.assertNotIn(data['machine_id'], json.dumps(records))

    def test_unknown_http200_keeps_exact_bounded_text_without_accepting_it(self):
        data = self.s._payload(self.cfg, True)
        for text in ['RETURN MESSAGE only\n', '', '<html>server error</html>', '{"status":"INSERTED"}',
                     ' RETURN INSERTED\n', '\ufeffRETURN INSERTED\r\n']:
            records = []
            with self.subTest(text=text), self.assertRaises(G.MapError):
                G.post(data, lambda *a, **k: self.response(text.encode()), record=records.append)
            self.assertEqual(records[-1]['body'], text)
            self.assertEqual(records[-1]['outcome'], 'protocol_ambiguous')
            self.assertEqual(records[-1]['http_status'], 200)
            self.assertNotIn('terminal_result', records[-1])
        self.assertTrue(G.post(data, lambda *a, **k: self.response(b'\r\nRETURN INSERTED\r\n'))['ok'])

    def test_diagnostic_truncation_does_not_change_parser_limits(self):
        data = self.s._payload(self.cfg, True)
        body = b'x' * (G.MAX_DIAGNOSTIC_BODY + 10) + b'\nRETURN UPDATED 1 5\n'
        records = []
        result = G.post(data, lambda *a, **k: self.response(body), record=records.append)
        self.assertTrue(result['ok'])
        self.assertTrue(records[-1]['body_truncated'])
        self.assertEqual(len(records[-1]['body']), G.MAX_DIAGNOSTIC_BODY)
        self.assertEqual(records[-1]['terminal_result']['status'], 'UPDATED')
        records = []
        with self.assertRaises(G.MapError):
            G.post(data, lambda *a, **k: self.response(b'x'*(G.MAX_RESPONSE+500)), record=records.append)
        self.assertEqual(records[-1]['bytes_read'], G.MAX_RESPONSE+1)
        self.assertTrue(records[-1]['response_limit_exceeded'])
        self.assertEqual(len(records[-1]['body']), G.MAX_DIAGNOSTIC_BODY)
        self.assertEqual(records[-1]['outcome'], 'protocol_ambiguous')

    def test_private_identifier_redacted_before_truncation_and_in_parsed_messages(self):
        data = self.s._payload(self.cfg, True); identifier = data['machine_id']
        records = []
        body = 'RETURN ERROR ' + identifier.upper() + '\nRETURN MESSAGE ' + identifier
        result = G.post(data, lambda *a, **k: self.response(body.encode(), {'Content-Type':identifier}), record=records.append)
        self.assertNotIn(identifier.lower(), json.dumps([records,result]).lower())
        self.assertIn('[installation-id]', records[-1]['body'])
        for encoded in [''.join('\\u%04x'%ord(c) for c in identifier),
                        ''.join('&#%d;'%ord(c) for c in identifier),
                        ''.join('%%%02x'%ord(c) for c in identifier)]:
            records = []
            with self.assertRaises(G.MapError):
                G.post(data, lambda *a, **k: self.response(encoded.encode()), record=records.append)
            self.assertIn('withheld', records[-1]['body'])
        records = []
        body = 'x'*(G.MAX_DIAGNOSTIC_BODY-4)+identifier
        with self.assertRaises(G.MapError):
            G.post(data, lambda *a, **k: self.response(body.encode()), record=records.append)
        self.assertFalse(records[-1]['body'].endswith(identifier[:4]))

    def test_http_and_transport_errors_retain_distinct_diagnostics(self):
        data = self.s._payload(self.cfg, True); records = []
        def http_error(*args, **kwargs):
            raise error.HTTPError(G.ENDPOINT, 503, 'unavailable', {'Content-Type':'text/html'}, io.BytesIO(b'<html>unavailable</html>'))
        with self.assertRaises(G.MapError):G.post(data, http_error, record=records.append)
        self.assertEqual(records[-1]['http_status'],503)
        self.assertEqual(records[-1]['outcome'],'http_error')
        self.assertEqual(records[-1]['body'],'<html>unavailable</html>')
        records = []; calls = []
        def timeout(*args, **kwargs):calls.append(1);raise TimeoutError()
        with self.assertRaises(G.MapError):G.post(data,timeout,record=records.append)
        self.assertEqual(len(calls),1)
        self.assertIsNone(records[-1]['http_status'])
        self.assertEqual(records[-1]['outcome'],'transport_ambiguous')
        self.assertNotIn(data['machine_id'],json.dumps(records))

    def test_body_read_failure_retains_headers_without_retry(self):
        data=self.s._payload(self.cfg,True);records=[]
        response=self.response(b'')
        with patch.object(response,'read',side_effect=TimeoutError()),self.assertRaises(G.MapError):
            G.post(data,lambda *a,**k:response,record=records.append)
        self.assertEqual(records[-1]['http_status'],200)
        self.assertEqual(records[-1]['content_type'],'text/plain; charset=utf-8')
        self.assertTrue(records[-1]['body_read_failed'])
        self.assertEqual(records[-1]['outcome'],'transport_ambiguous')

    def test_response_body_committed_before_parser_failure(self):
        self.s.opener=lambda *a,**k:self.response(b'<html>diagnostic fixture</html>')
        def fail_after_check(text,deleting=False):
            self.assertFalse(db.session().in_transaction())
            task=IndiAllSkyDbTaskQueueTable.query.order_by(IndiAllSkyDbTaskQueueTable.id.desc()).first()
            self.assertEqual(task.data['response_evidence']['body'],text)
            self.assertEqual(task.data['response_evidence']['outcome'],'unparsed')
            raise G.MapError('No terminal RETURN status in map response')
        with patch.object(G,'parse_response',side_effect=fail_after_check):
            task,result=self.run_job()
        self.assertEqual(task.data['response_evidence']['outcome'],'protocol_ambiguous')
        self.assertFalse(result['ok']);self.assertTrue(self.s.state()['needs_review'])

    def test_latest_failure_survives_routine_task_cleanup(self):
        self.s.opener=lambda *a,**k:self.response(b'<html>keep after task cleanup</html>')
        task,_=self.run_job();identifier=self.s.identifier()
        expected=copy.deepcopy(task.data['response_evidence'])
        db.session.delete(task);db.session.commit()
        self.assertEqual(self.s.status()['response_evidence'],expected)
        self.assertTrue(self.s.state()['needs_review']);self.assertIsNone(self.s.schedule())
        self.assertNotIn(identifier,self.s._read(G.RESPONSE_KEY))

    def test_control_character_body_obeys_state_json_storage_budget(self):
        self.s.opener=lambda *a,**k:self.response(b'\x00'*G.MAX_DIAGNOSTIC_BODY)
        task,result=self.run_job()
        self.assertFalse(result['ok'])
        self.assertLessEqual(len(self.s._read(G.RESPONSE_KEY)),4096)
        self.assertTrue(task.data['response_evidence']['body_truncated'])
        self.assertEqual(self.s.status()['response_evidence'],task.data['response_evidence'])

    def test_failure_is_durable_private_and_review_can_be_followed_by_explicit_register(self):
        self.s.opener=lambda *a,**k:self.response(b'<html>unexpected HTTP200 body</html>')
        first,result=self.run_job();first_id=first.id
        self.assertFalse(result['ok']);self.assertTrue(self.s.state()['needs_review'])
        self.assertIsNone(self.s.schedule())
        db.session.expire_all();first=db.session.get(IndiAllSkyDbTaskQueueTable,first_id)
        saved=copy.deepcopy(first.data)
        self.assertEqual(saved['response_evidence']['http_status'],200)
        self.assertEqual(saved['response_evidence']['outcome'],'protocol_ambiguous')
        self.assertEqual(self.s.status()['response_evidence'],saved['response_evidence'])
        self.assertNotIn(self.s.identifier(),json.dumps([first.data,self.s.state(),self.s.status(),first.result]))
        # No reset is needed: only explicit previewed manual Register may proceed.
        self.now+=G.MIN_INTERVAL+1
        preview=self.s.preview();second_id=self.s.enqueue('register',preview['preview_token'])
        self.assertTrue(self.s.state()['needs_review'])  # Not silently cleared on enqueue.
        second=db.session.get(IndiAllSkyDbTaskQueueTable,second_id);second.setRunning()
        self.s.opener=lambda *a,**k:self.response(b'RETURN INSERTED\n')
        self.assertTrue(self.s.execute(second,**second.data['kwargs'])['ok'])
        self.assertFalse(self.s.state()['needs_review']);self.assertTrue(self.s.state()['registered'])
        self.assertEqual(len(self.s.state()['attempts']),2)
        db.session.expire_all()
        self.assertEqual(db.session.get(IndiAllSkyDbTaskQueueTable,first_id).data,saved)


if __name__=='__main__':unittest.main()
