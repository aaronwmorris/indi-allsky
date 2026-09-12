from queue import Queue

from indi_allsky.capture_control import drain_worker_control_queue
from indi_allsky.capture_control import request_worker_stop


class _Worker:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive


def test_stop_request_is_queued_once_for_a_live_worker():
    control_queue = Queue()
    worker = _Worker()

    requested, queued = request_worker_stop(worker, control_queue)
    requested_again, queued_again = request_worker_stop(
        worker,
        control_queue,
        already_requested=requested,
    )

    assert (requested, queued) == (True, True)
    assert (requested_again, queued_again) == (True, False)
    assert control_queue.get_nowait() == {'stop': True}
    assert control_queue.empty()


def test_stop_request_is_not_latched_without_a_live_worker():
    control_queue = Queue()

    assert request_worker_stop(None, control_queue) == (False, False)
    assert request_worker_stop(_Worker(alive=False), control_queue) == (False, False)
    assert control_queue.empty()


def test_control_queue_drains_all_messages_and_stop_wins():
    control_queue = Queue()
    control_queue.put({'settime': '5'})
    control_queue.put({'unexpected': True})
    control_queue.put({'stop': True})
    control_queue.put({'settime': '-3'})

    result = drain_worker_control_queue(control_queue)

    assert result == (True, -3, [{'unexpected': True}])
    assert control_queue.empty()
