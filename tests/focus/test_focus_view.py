"""`/focus` is today's page, with a link to the live page (`/focus/live`) when the rig can run it, else the reason.

App tier. The real app and the real `FocusView`; `TemplateView.__init__` (database: camera row, latest image) and
`TemplateView.get_context` (status text, astrometry) are replaced by stand-ins. The link side is a real `LinkServer`
when the test wants it up. The admin check is the real `verify_admin_network()`.
"""

from __future__ import annotations

import re
import types

import pytest

from indi_allsky.focus.link import LinkServer
from indi_allsky.focus.rigs import RigDecision
from indi_allsky.focus.rigs import decide


pytestmark = pytest.mark.app

ADMIN_IP = '127.0.0.1'
OUTSIDE_IP = '203.0.113.9'


class _Camera(object):
    id = 1
    name = 'ZWO CCD ASI294MC'


@pytest.fixture
def page(flask_app, sock_path, closers, monkeypatch):
    from indi_allsky.flask import base_views

    state = {'config': {'CAMERA_INTERFACE': 'indi', 'FOCUSER': {}}}

    def init(self, template_name, **kwargs):
        base_views.BaseView.__init__(self, **kwargs)
        self.template_name = template_name
        self.indi_allsky_config = state['config']
        self.camera = _Camera()

    monkeypatch.setattr(base_views.TemplateView, '__init__', init)

    def base_context(self):
        return {
            'website_title': 'test', 'page_title': self.page_title, 'camera_id': self.camera.id,
            'form_camera_select': types.SimpleNamespace(CAMERA_SELECT=lambda **kw: ''),  # the real form queries the database
        }

    monkeypatch.setattr(base_views.TemplateView, 'get_context', base_context)

    class Page(object):
        config = state['config']

        def link_up(self):
            s = LinkServer(sock_path)
            s.start()
            closers.append(s)

        def get(self, remote_addr=ADMIN_IP, admin=True, path='/indi-allsky/focus/live'):
            flask_app.set_user(is_admin=admin)
            with flask_app.app.test_client() as client:
                resp = client.get(path, environ_base={'REMOTE_ADDR': remote_addr})
            self.location = resp.headers.get('Location')
            return resp.status_code, resp.get_data(as_text=True)

        def classic(self, **kw):
            return self.get(path='/indi-allsky/focus', **kw)

    return Page()


def test_classic_for_indi_passive_with_reason(page):
    page.link_up()
    page.config['CAMERA_INTERFACE'] = 'indi_passive'
    reason = decide('indi_passive', _Camera.name, None, True).reason
    assert reason

    status, html = page.classic()

    assert status == 200
    assert reason in html
    assert 'id="focus-chart"' in html  # today's page
    assert 'data-focus-session' not in html


def test_classic_when_link_down_with_reason(page):
    reason = decide('indi', _Camera.name, None, False).reason

    status, html = page.classic()

    assert status == 200
    assert reason in html
    assert 'id="focus-chart"' in html
    assert 'data-focus-session' not in html


def test_reason_is_html_escaped(page, monkeypatch):
    from indi_allsky.flask import views
    monkeypatch.setattr(views, 'decide', lambda *a, **k: RigDecision('classic', None, '<b>x</b> & y'))

    status, html = page.classic()

    assert '&lt;b&gt;x&lt;/b&gt; &amp; y' in html
    assert '<b>x</b>' not in html


def test_classic_page_without_reason_has_no_banner(page, monkeypatch):
    from indi_allsky.flask import views
    monkeypatch.setattr(views, 'decide', lambda *a, **k: RigDecision('classic', None, ''))

    status, html = page.classic()

    assert status == 200
    assert 'focus-reason' not in html


def test_focus_links_to_the_live_page_when_the_rig_can_run_it(page):
    page.link_up()

    status, html = page.classic()

    assert status == 200
    assert 'id="focus-chart"' in html  # today's page stays the Focus page
    assert 'class="focus-live-link' in html
    assert 'href="/indi-allsky/focus/live" class="tw:btn tw:btn-sm tw:btn-primary tw:rounded-full">Live Focus</a>' in html
    assert 'data-focus-session' not in html


def test_focus_has_no_link_when_the_rig_cannot(page):
    status, html = page.classic()  # the link is down

    assert 'focus-live-link' not in html
    assert '>Live Focus</a>' not in html


def test_menu_lists_live_under_focus_on_every_rig(page):
    status, html = page.classic()  # the link is down: the live page itself sends the user back here

    focus = html.index('href="/indi-allsky/focus"')
    live = html.index('href="/indi-allsky/focus/live"')
    assert focus < live < html.index('Process FITS')
    assert 'id="menu-focus-children"' in html
    assert '>Live</a>' in html[live:live + 400]


def test_live_page_sends_a_rig_that_cannot_back_to_focus(page):
    status, html = page.get()  # the link is down

    assert status == 302
    assert page.location.endswith('/indi-allsky/focus')


def test_live_page_links_back_and_has_the_advanced_switch(page):
    page.link_up()

    status, html = page.get()

    assert 'href="/indi-allsky/focus" class="tw:btn tw:btn-sm tw:btn-outline tw:rounded-full">&larr; Focus</a>' in html
    assert 'id="fs-advanced"' in html
    assert '.fs:not(.fs-advanced) .fs-adv { display: none !important; }' in html


def test_new_page_idle_shows_start_only_for_admin_network(page):
    page.link_up()

    status, html = page.get(remote_addr=ADMIN_IP, admin=True)
    assert status == 200
    assert 'data-focus-session' in html
    assert 'id="focus-start"' in html

    status, html = page.get(remote_addr=OUTSIDE_IP, admin=True)
    assert 'data-focus-session' in html
    assert 'id="focus-start"' not in html

    status, html = page.get(remote_addr=ADMIN_IP, admin=False)
    assert 'id="focus-start"' not in html


def test_new_page_first_guess_at_the_motor_and_passes_the_ws_url(page):
    page.link_up()
    page.config['FOCUSER'] = {'CLASSNAME': 'focuser_x', 'GEAR_MOTOR_TEETH': 12, 'GEAR_LENS_TEETH': 82, 'TRAVEL_LIMIT_LENS_DEGREES': 30}

    status, html = page.get()
    assert 'data-motor-configured="1"' in html
    assert 'data-motor-reason=""' in html
    assert '<div id="fs-lens" class="fs-panel tw:flex tw:flex-col tw:gap-2" >' in html  # shown
    assert '<div id="fs-hand" class="fs-panel fs-adv" hidden>' in html
    assert '<div id="fs-idle-lens" class="fs-panel fs-ctl" >' in html
    assert '<button type="button" id="focus-start-af" class="tw:btn tw:btn-primary" ><span class="fs-label">Autofocus</span></button>' in html
    assert 'Press Play to move the lens and watch the stars.' in html
    assert 'data-ws-url="ws://localhost/indi-allsky/ws/focus"' in html

    page.config['FOCUSER'] = {}
    status, html = page.get()
    assert 'data-motor-configured="0"' in html
    assert '<div id="fs-lens" class="fs-panel tw:flex tw:flex-col tw:gap-2" hidden>' in html
    assert '<div id="fs-hand" class="fs-panel fs-adv" >' in html
    assert '<div id="fs-idle-lens" class="fs-panel fs-ctl" hidden>' in html


def test_a_motor_without_its_gears_says_what_to_set(page):
    page.link_up()
    page.config['FOCUSER'] = {'CLASSNAME': 'focuser_x', 'GEAR_MOTOR_TEETH': 0, 'GEAR_LENS_TEETH': 82,
                              'TRAVEL_LIMIT_LENS_DEGREES': 30}

    status, html = page.get()

    assert 'data-motor-reason="Set the focuser&#39;s gear teeth in Config."' in html
    assert '<p id="fs-idle-hint" class="fs-hint">Set the focuser&#39;s gear teeth in Config.</p>' in html
    assert '<button type="button" id="focus-start-af" class="tw:btn tw:btn-primary" disabled>' in html
    assert 'Press Play to move the lens' not in html


def test_the_graph_waits_for_an_autofocus_and_details_are_advanced(page):
    page.link_up()
    page.config['FOCUSER'] = {'CLASSNAME': 'focuser_x', 'GEAR_MOTOR_TEETH': 12, 'GEAR_LENS_TEETH': 82, 'TRAVEL_LIMIT_LENS_DEGREES': 30}

    status, html = page.get()

    assert '<div id="fs-graph-panel" class="fs-adv tw:flex tw:flex-col tw:gap-2" hidden>' in html
    for marked in ('<svg id="fs-rings" class="fs-adv"', 'id="fs-mode" class="fs-mode fs-muted fs-adv"',
                   '<div class="fs-cam fs-adv">', 'id="fs-stars-pop" class="fs-panel fs-slider fs-adv"',
                   'id="fs-repick"'):
        assert marked in html, marked
    # the lens buttons stay in simple mode: outside the graph panel
    lens_part = html.split('id="fs-graph-panel"', 1)[1]
    assert lens_part.index('id="fs-clear"') < lens_part.index('id="fs-lens-in"') < lens_part.index('id="fs-af-btn"')


def test_idle_page_without_a_recent_picture_has_a_black_box(page):
    page.link_up()

    status, html = page.get()

    assert 'data-focus-session' in html
    assert '<span class="fs-tag">No recent picture</span>' in html
    assert '<div class="fs-poster">' in html and 'alt="The last sky picture"' not in html
    # the poster is a still: none of the Focus page's polling picture
    for gone in ('data-poll-url', 'id="image-canvas"', 'id="focus-score"', 'id="REFRESH_SELECT"', 'id="ZOOM_SELECT"',
                 'id="fs-idle-wait"', 'Loading latest picture'):
        assert gone not in html, gone


def test_idle_page_shows_the_last_picture_with_play_on_it(page, monkeypatch):
    import datetime
    from indi_allsky.flask import views

    entry = types.SimpleNamespace(createDate=datetime.datetime(2026, 11, 24, 21, 14, 5),
                                  getUrl=lambda **kw: 'images/ccd_x/20261124/21/img.jpg')
    monkeypatch.setattr(views.FocusLiveView, 'latest_image_entry', entry, raising=False)
    page.link_up()

    status, html = page.get()

    assert '<img src="/indi-allsky/images/ccd_x/20261124/21/img.jpg" alt="The last sky picture">' in html
    assert '<span class="fs-tag">Last picture &middot; 21:14</span>' in html
    play = html.split('id="focus-start"', 1)[1].split('</button>', 1)[0]
    assert 'class="fs-play" aria-label="Start Live Preview"' in play
    assert '<span class="fs-label">Start Live Preview</span>' in play

    status, html = page.get(remote_addr=OUTSIDE_IP)
    assert 'alt="The last sky picture"' in html  # a watcher sees the picture, with no Play
    assert 'id="focus-start"' not in html


def test_new_page_has_the_live_view_and_its_script(page):
    page.link_up()
    page.config['FOCUSER'] = {'CLASSNAME': 'focuser_x', 'GEAR_MOTOR_TEETH': 12, 'GEAR_LENS_TEETH': 82, 'TRAVEL_LIMIT_LENS_DEGREES': 30}

    status, html = page.get()

    assert status == 200
    for element in ('fs-idle', 'fs-live', 'fs-canvas', 'fs-rings', 'fs-age', 'fs-stxt', 'fs-value', 'fs-sub',
                    'fs-stars-pop', 'fs-snr', 'fs-exp', 'fs-gain', 'fs-apply', 'fs-region-btn',
                    'fs-region', 'fs-warn', 'fs-keep-going', 'fs-save', 'fs-cancel', 'fs-af-save', 'focus-start',
                    'fs-toast', 'fs-ended',
                    'fs-tune', 'fs-pic-wait', 'fs-step-bar', 'fs-stages', 'fs-steps', 'fs-af', 'fs-af-title',
                    'fs-af-bar', 'fs-af-left', 'fs-af-stages', 'fs-af-msg', 'fs-graph-panel', 'fs-g-size', 'fs-g-lens',
                    'fs-graph', 'fs-g-note', 'fs-lens-in', 'fs-lens-out', 'fs-lens-size', 'fs-af-btn',
                    'fs-bestfit', 'fs-back', 'fs-clear', 'fs-motor-reason', 'fs-hand', 'fs-trace', 'fs-next-motor',
                    'fs-next-hand', 'fs-idle-lens', 'fs-idle-in', 'fs-idle-out', 'fs-idle-size', 'fs-idle-hint',
                    'focus-start-af', 'fs-confirm', 'fs-confirm-yes', 'fs-confirm-no'):
        assert 'id="{0:s}"'.format(element) in html, element
    for gone in ('id="fs-pick"', 'FOCUS_CCW', 'FOCUS_CW', 'STEP_DEGREES', 'data-motor-url', 'ajax/focuscontroller',
                 'Autofocus comes in a later update.', 'Inward/Outward'):
        assert gone not in html, gone  # the lens is capture's now
    # the script's address changes with the file, so a deploy never leaves a browser on the old script
    assert re.search(r'js/focus_session\.js\?v=\d+"', html)
    assert '<span class="fs-label">Start Live Preview</span>' in html
    assert '<span class="fs-tag fs-tag-live">LIVE</span>' in html
    assert 'Normal pictures pause while you focus.' not in html  # the start question says it now
    assert '>Save focus</button>' in html and '>Cancel</button>' in html
    assert 'End session' not in html  # Cancel replaced it: the only ways out are Save and Cancel
    assert 'Press Autofocus, or nudge the lens and watch the star size.' in html
    assert 'Starting live video' in html
    assert 'aria-label="Star size against lens position"' in html


def test_the_focus_controls_have_a_small_heading(page):
    page.link_up()
    page.config['FOCUSER'] = {'CLASSNAME': 'focuser_x', 'GEAR_MOTOR_TEETH': 12, 'GEAR_LENS_TEETH': 82, 'TRAVEL_LIMIT_LENS_DEGREES': 30}

    status, html = page.get()

    assert '<div class="fs-ctl" role="group" aria-labelledby="fs-ctl-h">' in html
    assert '<h3 id="fs-ctl-h" class="fs-ctl-h">Focus controls</h3>' in html
    group = html.split('id="fs-ctl-h"', 1)[1]
    assert group.index('id="fs-lens-size"') < group.index('id="fs-lens-in"') < group.index('id="fs-af-btn"')

    status, html = page.get(remote_addr=OUTSIDE_IP)
    assert 'Focus controls' not in html  # a watcher has none


def test_new_page_without_motor_has_the_trace(page):
    page.link_up()

    status, html = page.get()

    assert 'id="fs-trace"' in html
    assert 'data-motor-configured="0"' in html
    assert 'Turn the focus by hand and watch the size fall.' in html
    assert 'Autofocus comes in a later update.' not in html


def test_watchers_get_no_controls(page):
    page.link_up()
    page.config['FOCUSER'] = {'CLASSNAME': 'focuser_x', 'GEAR_MOTOR_TEETH': 12, 'GEAR_LENS_TEETH': 82, 'TRAVEL_LIMIT_LENS_DEGREES': 30}

    for remote_addr, admin in ((OUTSIDE_IP, True), (ADMIN_IP, False)):
        status, html = page.get(remote_addr=remote_addr, admin=admin)

        assert status == 200
        assert 'No focus session is running. An admin can start one.' in html
        for element in ('focus-start', 'fs-save', 'fs-cancel', 'fs-af-save', 'fs-next', 'fs-pick', 'fs-keep-going', 'fs-apply', 'fs-region',
                        'fs-exp-btn', 'fs-region-btn', 'fs-snr', 'fs-stars-chip', 'fs-stretch-btn', 'fs-stretch-pop',
                        'fs-relevel', 'fs-black', 'fs-white', 'fs-tune', 'fs-lens-in', 'fs-lens-out', 'fs-lens-size',
                        'fs-af-btn', 'fs-bestfit', 'fs-back', 'fs-clear', 'focus-start-af', 'fs-idle-lens', 'fs-idle-in',
                        'fs-confirm'):
            assert 'id="{0:s}"'.format(element) not in html, element
        assert 'id="fs-graph"' in html and 'id="fs-steps"' in html  # they still see the graph and the steps
        assert 'js/focus_session.js' in html  # they still watch


def test_stills_rig_shows_the_reason(page):
    page.link_up()
    page.config['CAMERA_INTERFACE'] = 'mqtt_imx477'

    status, html = page.get()

    assert status == 200
    assert 'data-focus-session' in html
    assert 'live video is not available for this camera type' in html
    # whether Move region is offered on a stills rig is the page's call: test_focus_page_js pins canMoveRegion
