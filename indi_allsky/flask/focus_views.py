"""`/ws/focus`: relays a focus page's websocket to the capture process's focus link.

One `LinkClient` per page. Three threads per connection:
  - link reader: link -> a per-connection `NewestSlot` (frames newest-only, JSON always kept, in order);
  - page sender: slot -> websocket (JSON as text, frames as binary, both unchanged);
  - the request thread: websocket -> link (page commands).
When either side goes away all three stop; every blocking call has a timeout, so none waits forever.

Whether a page may command is decided here, once, and sent in the link hello as `controls`: an admin user on an admin
network. A page cannot claim it: every page message has its `controls` key removed before it is forwarded.

Message bodies and request headers are never logged, because they can carry what a client sent; errors log only the exception type.
"""

import json
import threading
import time

from flask import request
from flask import current_app as app

from flask_login import login_required
from flask_login import current_user

from .base_views import BaseView

from ..focus.link import DEFAULT_ADDRESS
from ..focus.link import LinkClient
from ..focus.link import LinkUnavailable
from ..focus.link import NewestSlot
from ..focus.link import SlotOverflow


# The reason shown when the page cannot reach the capture program (the last row of the rig table).
LINK_UNREACHABLE_REASON = ('The live focus page cannot reach the capture program. It may be stopped, or running in '
                           'another container or on another machine.')

# `ended` reason when the page reads too slowly and its JSON queue fills (a code, like the controller's reasons).
SLOW_REASON = 'slow'

PAGE_MSG_MAX = 4096      # bytes, UTF-8; larger page messages are dropped
WS_MSG_MAX = 64 * 1024    # simple_websocket closes the connection over this
POLL_S = 0.5              # every blocking wait wakes at least this often to check for shutdown
JOIN_TIMEOUT_S = 2.0
FLUSH_TIMEOUT_S = 2.0     # how long a too-slow page gets to take its final `ended`

# Messages after which capture sends nothing more to this page.
_FINAL_KINDS = ('ended', 'refused')


def focus_address():
    return app.config.get('INDI_ALLSKY_FOCUS_ADDRESS', DEFAULT_ADDRESS)


SESSION_CHECK_TIMEOUT_S = 1.0


def focus_session_running(path=None, timeout=SESSION_CHECK_TIMEOUT_S) -> bool:
    """True when capture says a focus session runs. Used to keep other motor commands off the lens.

    Joins as a page without controls for a moment and reads the first `state`. A missing link, or no answer
    within the timeout, counts as no session: a running session services the link several times a second.
    """
    link = LinkClient(path or focus_address(), timeout=timeout)
    try:
        link.connect(hello={'controls': False})
    except LinkUnavailable:
        return False
    try:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            msg = link.recv(timeout=remaining)
            if msg is None:
                return False
            what, body = msg
            if what == 'json' and isinstance(body, dict) and body.get('kind') == 'state':
                return body.get('session') == 'active'
    except LinkUnavailable:
        return False
    finally:
        link.close()


def _encode(obj):
    return json.dumps(obj, separators=(',', ':'))


class FocusRelay(object):
    """Moves messages between one page's websocket and its `LinkClient` until either side closes.

    `ws` needs `receive(timeout)` (None on timeout, raises `closed_exc` once closed), `send(str | bytes)` and
    `close()`, as `simple_websocket.Server` has.
    """

    def __init__(self, ws, link, logger, closed_exc):
        self.ws = ws
        self.link = link
        self.logger = logger
        self.closed_exc = closed_exc
        self.slot = NewestSlot()
        self._stop = threading.Event()       # any side asks for teardown
        self._link_done = threading.Event()  # the reader will put nothing more in the slot
        self._sender_done = threading.Event()

    def run(self):
        reader = threading.Thread(target=self._link_reader, name='focus-ws-link', daemon=True)
        sender = threading.Thread(target=self._page_sender, name='focus-ws-send', daemon=True)
        reader.start()
        sender.start()
        try:
            self._page_reader()
        finally:
            self._stop.set()
            self.link.close()
            reader.join(JOIN_TIMEOUT_S)
            sender.join(JOIN_TIMEOUT_S)
            self._close_ws()

    def _close_ws(self):
        try:
            self.ws.close()
        except Exception:
            pass

    # -- link -> slot -------------------------------------------------------------

    def _link_reader(self):
        final_seen = False
        slow = False
        try:
            while not self._stop.is_set():
                msg = self.link.recv(timeout=POLL_S)
                if msg is None:
                    continue
                what, body = msg
                if what == 'frame':
                    self.slot.put_frame(body)
                    continue
                self.slot.put_json(_encode(body).encode('utf-8'))
                if isinstance(body, dict) and body.get('kind') in _FINAL_KINDS:
                    final_seen = True
        except LinkUnavailable:
            pass
        except SlotOverflow:
            self.logger.warning('Focus page too slow to keep up; closing it')
            # Throw away what it has not read, and tell it why it is being closed.
            while self.slot.get(timeout=0) is not None:
                pass
            self.slot.put_json(_encode({'kind': 'ended', 'reason': SLOW_REASON}).encode('utf-8'))
            final_seen = True
            slow = True
        except Exception as e:
            self.logger.error('Focus page link reader failed: %s', type(e).__name__)
            self._stop.set()
        finally:
            if not final_seen and not self._stop.is_set():
                # Capture went away without ending the session for this page.
                try:
                    self.slot.put_json(_encode({'kind': 'ended', 'reason': LINK_UNREACHABLE_REASON}).encode('utf-8'))
                except SlotOverflow:
                    pass
            self._link_done.set()
            if slow:
                # The sender stops by itself once the slot is empty; a page that will not take even this is cut off.
                self._sender_done.wait(FLUSH_TIMEOUT_S)
                self._stop.set()

    # -- slot -> page -------------------------------------------------------------

    def _page_sender(self):
        try:
            while not self._stop.is_set():
                entry = self.slot.get(timeout=POLL_S)
                if entry is None:
                    if not self._link_done.is_set():
                        continue
                    # The reader is finished; whatever it put before saying so is in the slot now.
                    entry = self.slot.get(timeout=0)
                    if entry is None:
                        break
                what, payload = entry
                self.ws.send(payload.decode('utf-8') if what == 'json' else payload)
        except self.closed_exc:
            pass
        except Exception as e:
            self.logger.error('Focus page send failed: %s', type(e).__name__)
        finally:
            self._stop.set()
            self._sender_done.set()
            # Wakes nothing by itself (the page reader polls), but tells the browser the session is over.
            self._close_ws()

    # -- page -> link -------------------------------------------------------------

    def _page_reader(self):
        while not self._stop.is_set():
            try:
                message = self.ws.receive(timeout=POLL_S)
            except self.closed_exc:
                return
            except Exception as e:
                self.logger.error('Focus page receive failed: %s', type(e).__name__)
                return
            if message is None:
                continue
            command = self._command_from_page(message)
            if command is None:
                continue
            try:
                self.link.send(command)
            except (LinkUnavailable, ValueError):
                return

    def _command_from_page(self, message):
        """The dict to forward, or None to drop. Never logs the message."""
        if not isinstance(message, str):
            self.logger.debug('Focus page message dropped: binary')
            return None
        if len(message.encode('utf-8')) > PAGE_MSG_MAX:
            self.logger.debug('Focus page message dropped: over %d bytes', PAGE_MSG_MAX)
            return None
        try:
            command = json.loads(message)
        except (ValueError, RecursionError):  # RecursionError: deep nesting, on Python 3.9's scanner
            self.logger.debug('Focus page message dropped: not JSON')
            return None
        if not isinstance(command, dict):
            self.logger.debug('Focus page message dropped: not an object')
            return None
        command.pop('controls', None)  # only the hello carries it, set by this view
        return command


class WsFocusView(BaseView):
    decorators = [login_required]

    def dispatch_request(self):
        import simple_websocket

        logger = app.logger
        controls = bool(current_user.is_authenticated and current_user.is_admin and self.verify_admin_network())

        link = LinkClient(focus_address())
        try:
            link.connect(hello={'controls': controls})
        except LinkUnavailable as e:
            logger.info('Focus page: capture link unavailable (%s)', e.reason)
            link = None

        try:
            ws = simple_websocket.Server.accept(request.environ, max_message_size=WS_MSG_MAX)
        except BaseException:
            # the relay never starts, so nothing else closes the link: capture would keep a page that is not there
            if link is not None:
                link.close()
            raise

        if link is None:
            try:
                ws.send(_encode({'kind': 'ended', 'reason': LINK_UNREACHABLE_REASON}))
            except Exception as e:
                logger.info('Focus page left before the link reason was sent: %s', type(e).__name__)
            try:
                ws.close()
            except Exception:
                pass
            return ''

        logger.info('Focus page connected (controls: %s)', controls)
        try:
            FocusRelay(ws, link, logger, simple_websocket.ConnectionClosed).run()
        finally:
            link.close()
        logger.info('Focus page disconnected')
        return ''
