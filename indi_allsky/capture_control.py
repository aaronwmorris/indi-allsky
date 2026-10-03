"""Small, dependency-free helpers shared by capture worker processes."""

import queue


def request_worker_stop(worker, control_queue, already_requested=False):
    """Queue one graceful stop request and report whether a live worker has it.

    The caller keeps ``already_requested`` because multiprocessing queues do
    not offer a reliable, race-free way to inspect pending commands.
    """
    if worker is None or not worker.is_alive():
        return False, False
    if already_requested:
        return True, False

    control_queue.put({'stop': True})
    return True, True


def drain_worker_control_queue(control_queue):
    """Drain every pending command so a stop cannot sit behind stale updates."""
    stop_requested = False
    time_offset = None
    unknown_actions = []

    while True:
        try:
            action = control_queue.get(False)
        except queue.Empty:
            break

        if action.get('stop'):
            stop_requested = True
        elif action.get('settime'):
            time_offset = int(action['settime'])
        else:
            unknown_actions.append(action)

    return stop_requested, time_offset, unknown_actions
