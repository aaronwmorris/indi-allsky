"""Stale tabs, repeated clicks and malformed control payloads must be harmless."""
from copy import deepcopy
import json

from test_syncapi_archive_view import sync_endpoint


def test_invalid_types_and_speeds_leave_saved_settings_and_queue_untouched(sync_endpoint):
    env, client, _, headers = sync_endpoint
    saved = deepcopy(env.config)
    payloads = [{'action': 'start', 'types': value} for value in
                [None, 'image', 1, True, {}, [[]], [{}], [None], ['../../image'], ['IMAGE']]]
    payloads += [{'action': 'start', 'types': ['image'], 'upload_limit': value} for value in
                 ['128', -1, 1, True, float('nan'), float('inf'), [], {}]]
    for payload in payloads:
        response = client.post('/ajax/syncapi/run', data=json.dumps(payload),
                               content_type='application/json', headers=headers)
        assert response.status_code == 400, (payload, response.status_code)
        assert env.sync.active_task() is None and not env.calls
    assert env.config == saved


def test_null_speed_uses_saved_limit_without_changing_config(sync_endpoint):
    env, client, _, headers = sync_endpoint
    saved = deepcopy(env.config)
    result = client.post('/ajax/syncapi/run', json={'action': 'start', 'types': ['image'],
                                                 'upload_limit': None}, headers=headers)
    assert result.status_code == 200 and env.sync.active_task().data['upload_limit'] == 0
    assert env.config == saved and not env.calls


def test_click_storm_and_stale_cancel_do_not_start_or_cancel_an_extra_run(sync_endpoint):
    env, client, _, headers = sync_endpoint
    task_ids = []
    for index in range(30):
        result = client.post('/ajax/syncapi/run', json={'action': 'start',
            'types': ['image'] if index % 2 else ['panoramaimage']}, headers=headers)
        assert result.status_code == 200
        task_ids.append(result.get_json()['task_id'])
    assert len(set(task_ids)) == 1
    task = env.sync.active_task()
    task.setExpired()
    new = env.sync.request_sync(env.config, ['image'])
    for _ in range(10):
        result = client.post('/ajax/syncapi/run', json={'action': 'cancel', 'task_id': task_ids[0]}, headers=headers)
        assert result.status_code == 200 and not result.get_json()['cancel_requested']
    assert env.sync.active_task().id == new.id and not env.calls


def test_anonymous_requests_cannot_read_status_or_start_cancel(sync_endpoint):
    env, _, _, _ = sync_endpoint
    anonymous = env.app.test_client()
    assert anonymous.get('/ajax/syncapi/run').status_code == 401
    for action in ('start', 'cancel'):
        response = anonymous.post('/ajax/syncapi/run', json={'action': action, 'types': ['image']})
        assert response.status_code in (400, 401)
    assert env.sync.active_task() is None and not env.calls
