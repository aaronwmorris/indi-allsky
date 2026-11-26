"""The live Focus page's pure helpers (`focus_session.js`), run with node.

Pure tier. Skipped where node is not installed. The frame header is built with the same `struct` format as
`indi_allsky/focus/frame.py`, so the page and capture cannot drift apart unnoticed.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from indi_allsky.focus import frame


NODE = shutil.which('node')
SCRIPT = Path(__file__).resolve().parents[2] / 'indi_allsky' / 'flask' / 'static' / 'js' / 'focus_session.js'

pytestmark = pytest.mark.skipif(NODE is None, reason='node is not installed')


def run(body):
    """Run `body` with the helpers as `h`; it must print one JSON value."""
    code = 'const h = require({0:s});\n{1:s}\n'.format(json.dumps(str(SCRIPT)), body)
    out = subprocess.run([NODE, '-e', code], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def test_parse_header_matches_capture():
    header = struct.pack('>4sBIdffI', b'IAFF', 1, 4242, 1764000000.125, 0.25, 300.0, 77)
    assert len(header) == frame.HEADER.size
    buf = list(header + b'\xff\xd8jpeg')

    got = run('const b = new Uint8Array({0:s}).buffer; console.log(JSON.stringify(h.parseHeader(b)));'.format(
        json.dumps(buf)))

    assert got == {'frame_no': 4242, 'capture_time': 1764000000.125, 'exposure': 0.25, 'gain': 300.0, 'cmd_id': 77}


def test_parse_header_refuses_other_bytes():
    bad_magic = list(struct.pack('>4sBIdffI', b'XXXX', 1, 1, 0.0, 0.0, 0.0, 0))
    bad_version = list(struct.pack('>4sBIdffI', b'IAFF', 2, 1, 0.0, 0.0, 0.0, 0))

    got = run('console.log(JSON.stringify([{0:s}, {1:s}, [1, 2, 3]].map('
              'a => h.parseHeader(new Uint8Array(a).buffer))));'.format(json.dumps(bad_magic), json.dumps(bad_version)))

    assert got == [None, None, None]


def test_clock_offset_uses_the_shortest_round_trip():
    got = run('const s = [h.clockSample(10, 10.4, 1000.5), h.clockSample(20, 20.02, 1010.01),'
              ' h.clockSample(30, 30.3, 1020.0)]; console.log(JSON.stringify(h.bestOffset(s)));')

    assert got == pytest.approx(990.0)


def test_status_state():
    got = run('console.log(JSON.stringify([h.statusState(null, 0.1, false), h.statusState(0.05, 0.1, false),'
              ' h.statusState(0.05, 0.1, true), h.statusState(0.9, 0.1, false), h.statusState(1.1, 0.1, false),'
              ' h.statusState(6.1, 2, true)]));')

    assert got == ['waiting', 'live', 'waiting', 'live', 'stalled', 'stalled']


def test_ended_text_maps_codes_and_keeps_sentences():
    sentence = 'The live focus page cannot reach the capture program.'
    got = run('console.log(JSON.stringify(["done", "slow", {0:s}, null].map(h.endedText)));'.format(
        json.dumps(sentence)))

    assert got[0].startswith('The focus session ended')
    assert 'keep up' in got[1]
    assert got[2] == sentence
    assert got[3] == ''


def test_nearest_ring_within_screen_pixels():
    rings = [{'id': 0, 'x': 100, 'y': 100}, {'id': 1, 'x': 130, 'y': 100}]
    got = run('const r = {0:s}; console.log(JSON.stringify([h.nearestRing(r, 104, 100, 1, 12),'
              ' h.nearestRing(r, 120, 100, 1, 12), h.nearestRing(r, 115, 100, 2, 12)]));'.format(json.dumps(rings)))

    assert got == [0, 1, None]


def test_next_cmd_id_rises_and_wraps():
    got = run('console.log(JSON.stringify([h.nextCmdId(0, 0), h.nextCmdId(5, 9), h.nextCmdId(12, 3),'
              ' h.nextCmdId(4294967295, 0)]));')

    assert got == [1, 10, 13, 1]


def test_words():
    got = run('console.log(JSON.stringify([h.fmtAge(0.214), h.fmtAge(3.42), h.fmtAge(12.6), h.liveText("video", 0.1),'
              ' h.liveText("stills", 2), h.fmtExposure(0.075), h.fmtGain(300)]));')

    assert got == ['0.21 s old', '3.4 s old', '13 s old', 'Live video · 10 fps',
                   'Still pictures · 2 s each', '75 ms', '300']


def test_live_rate_is_what_arrives_not_one_over_exposure():
    got = run('console.log(JSON.stringify([h.liveText("video", 0.001, 0.1), h.liveText("video", 0.5, 0.1),'
              ' h.liveText("video", null, null), h.liveText("stills", null, null)]));')

    assert got == ['Live video · 10 fps', 'Live video · 2 fps', 'Live video',
                   'Still pictures']


def test_pending_commands_add_and_clear_on_the_picture_that_shows_them():
    got = run('let p = []; p = h.pendingAdd(p, 5, "camera"); p = h.pendingAdd(p, 6, "motor");'
              ' p = h.pendingAdd(p, 8, "region");'
              ' console.log(JSON.stringify([p.length, h.pendingShown(p, 4).length, h.pendingShown(p, 6),'
              ' h.pendingShown(p, 9)]));')

    assert got == [3, 3, [{'id': 8, 'kind': 'region'}], []]


def test_pending_drop_when_the_command_never_left():
    got = run('const p = [{id: 5, kind: "camera"}, {id: 6, kind: "motor"}];'
              ' console.log(JSON.stringify([h.pendingDrop(p, 6), h.pendingDrop(p, 99)]));')

    assert got == [[{'id': 5, 'kind': 'camera'}], [{'id': 5, 'kind': 'camera'}, {'id': 6, 'kind': 'motor'}]]


def test_pending_refused_by_id_or_newest_of_its_kind():
    got = run('const p = [{id: 5, kind: "camera"}, {id: 6, kind: "motor"}, {id: 7, kind: "camera"}];'
              ' console.log(JSON.stringify([h.pendingRefused(p, "set_camera", 5).map(x => x.id),'
              ' h.pendingRefused(p, "set_camera", null).map(x => x.id),'
              ' h.pendingRefused(p, "move_to", undefined).map(x => x.id),'
              ' h.pendingRefused(p, "start", null).map(x => x.id)]));')

    assert got == [[6, 7], [5, 6], [5, 7], [5, 6, 7]]


def test_exposure_choices_stay_inside_the_camera_limits():
    got = run('const L = [0.001, 0.01, 0.1, 1, 5, 10];'
              ' console.log(JSON.stringify([h.exposureChoices(L, 0.1, 0.005, 2),'
              ' h.exposureChoices(L, 0.1, null, null)]));')

    assert got == [[0.005, 0.01, 0.1, 1, 2], [0.001, 0.01, 0.1, 1, 5, 10]]


def test_gain_range_from_the_camera_with_a_fine_step_for_small_ranges():
    got = run('console.log(JSON.stringify([h.gainRange(0, 10, 2), h.gainRange(0, 510, 7),'
              ' h.gainRange(null, null, 100)]));')

    assert got[0] == {'min': 0, 'max': 10, 'step': pytest.approx(0.1)}
    assert got[1] == {'min': 0, 'max': 510, 'step': 1}
    assert got[2] == {'min': 0, 'max': 600, 'step': 1}


def test_gain_range_for_a_fixed_gain_camera_is_fixed():
    got = run('console.log(JSON.stringify([h.gainRange(1, 1, 1), h.gainRange(0, 0, 0), h.gainRange(0, 10, 2).fixed,'
              ' h.gainRange(null, null, 0).fixed]));')

    assert got[0] == {'min': 1, 'max': 1, 'step': 1, 'fixed': True}
    assert got[1] == {'min': 0, 'max': 0, 'step': 1, 'fixed': True}
    assert got[2:] == [None, None]


def test_gain_sent_stays_inside_the_camera_limits():
    got = run('const g = (lo, hi, cur, v) => h.clampGain(h.gainRange(lo, hi, cur), v);'
              ' console.log(JSON.stringify([g(1, 1, 100, 100), g(0, 300, 500, 500), g(0, 300, 500, 120),'
              ' g(null, null, 100, 100), g(null, null, 700, 700), h.gainRange(0, 300, 500).max]));')

    assert got == [1, 300, 120, 100, 700, 300]


def test_region_can_move_in_both_modes_even_without_a_region_yet():
    got = run('console.log(JSON.stringify([h.canMoveRegion({picture: "stills", roi: null}),'
              ' h.canMoveRegion({picture: "video", roi: [0, 0, 1024, 1024]}),'
              ' h.canMoveRegion({picture: "video", roi: null}), h.canMoveRegion(null),'
              ' h.canMoveRegion({picture: "classic", roi: null})]));')

    assert got == [True, True, True, False, False]


def test_fractional_gain_reads_sensibly():
    got = run('console.log(JSON.stringify([h.fmtGain(1.25), h.fmtGain(1.2), h.fmtGain(12.34)]));')

    assert got == ['1.25', '1.2', '12.3']


def test_first_picture_is_not_stalled_before_its_download():
    got = run('console.log(JSON.stringify([h.expectedGap(2, []), h.expectedGap(0.1, [0.5, 0.2, 0.3]),'
              ' h.expectedGap(2, [0.5])]));')

    assert got == [4, 0.3, 2]


def test_region_box_on_a_whole_frame_picture_is_centred_and_on_the_bayer_grid():
    got = run('console.log(JSON.stringify([h.regionBox(3000, 2000, null), h.regionBox(801, 601, null),'
              ' h.regionBox(3000, 2000, [2500, 100, 1024, 1024])]));')

    assert got[0] == {'x': 988, 'y': 488, 'w': 1024, 'h': 1024}
    assert got[1] == {'x': 100, 'y': 0, 'w': 600, 'h': 600}
    assert got[2] == {'x': 1976, 'y': 100, 'w': 1024, 'h': 1024}


def test_star_states_in_words():
    got = run('console.log(JSON.stringify(["kept", "weak", "dropped", "pinned", "saturated", "odd"]'
              '.map(h.starWord)));')

    assert got == ['measured', 'too faint', 'left out', 'the only one measured', 'too bright', 'odd']


def test_stretch_slider_ends_and_round_trip():
    got = run('const pos = [0, 1, 250, 500, 750, 999, 1000];'
              'console.log(JSON.stringify({ends: [h.levelFromSlider(0), h.levelFromSlider(1000)],'
              ' back: pos.map(p => h.sliderFromLevel(h.levelFromSlider(p))),'
              ' clamp: [h.levelFromSlider(-5), h.levelFromSlider(2000), h.sliderFromLevel(-1), h.sliderFromLevel(3)]}));')

    assert got['ends'] == [0, 1]
    assert got['back'] == [0, 1, 250, 500, 750, 999, 1000]
    assert got['clamp'] == [0, 1, 0, 1000]


def test_stretch_slider_gives_the_dark_end_most_of_the_travel():
    # the moonlit sky sat at 1-5 % of full scale: that band must span a good share of the slider, not a few steps
    got = run('console.log(JSON.stringify([h.sliderFromLevel(0.01), h.sliderFromLevel(0.05)]));')

    assert got[1] - got[0] >= 150
    assert 0 < got[0] < got[1] < 1000


def test_stretch_sliders_keep_black_under_white():
    got = run('console.log(JSON.stringify([h.orderSliders(300, 600, "black"), h.orderSliders(700, 600, "black"),'
              ' h.orderSliders(700, 600, "white"), h.orderSliders(1000, 1000, "black"), h.orderSliders(0, 0, "white")]));')

    assert got == [[300, 600], [700, 701], [599, 600], [999, 1000], [0, 1]]


def test_stretch_levels_in_words():
    got = run('console.log(JSON.stringify([h.fmtLevel(0.0025), h.fmtLevel(0.034), h.fmtLevel(0.5), h.fmtLevel(null)]));')

    assert got == ['0.25 %', '3.4 %', '50 %', '–']


def test_motor_info_reads_the_contract_object_and_the_old_bool():
    got = run('console.log(JSON.stringify([h.motorInfo({configured: true, ok: false, reason: "no driver"}),'
              ' h.motorInfo(true), h.motorInfo(false), h.motorInfo(null)]));')

    assert got[0] == {'configured': True, 'ok': False, 'reason': 'no driver'}
    assert got[1] == {'configured': True, 'ok': True, 'reason': None}
    assert got[2] == got[3] == {'configured': False, 'ok': False, 'reason': None}


def test_fit_model_has_its_plateau_and_needs_numbers_to_draw():
    fit = {'c': 50, 'a': 2, 'k': 0.1, 'P': 6, 'ok': True}
    got = run('const f = {0:s}; console.log(JSON.stringify([h.fitModel(f, 50), h.fitModel(f, 50 + 15),'
              ' h.fitModel(f, 500), h.drawableFit(f) !== null, h.drawableFit({{c: 1}}), h.drawableFit(null)]));'.format(
                  json.dumps(fit)))

    assert got[0] == pytest.approx(2)
    assert got[1] == pytest.approx(2.5)
    assert got[2] == 6
    assert got[3:] == [True, None, None]


def test_autofocus_estimate_follows_the_contract_formula():
    # here 0, limit 400: window 200, start -200, end 200; rate min(50, 8 / 0.5) = 16
    # (200 + 20) / 50 + 400 / 16 + 3 + 200 / 50 = 4.4 + 25 + 3 + 4 = 36.4, so 37
    lens = {'position': 0, 'limit': 400, 'speed': 50, 'backlash': 20, 'reachable': [-380, 400]}
    got = run('const l = {0:s}; console.log(JSON.stringify([h.autofocusEstimate(l, 0.5),'
              ' h.autofocusEstimate(l, null), h.autofocusLabel(37), h.autofocusLabel(null)]));'.format(json.dumps(lens)))

    assert got == [37, None, 'Autofocus · about 37 s', 'Autofocus']


def test_graph_target_snaps_to_best_fit_and_stays_reachable():
    got = run('const f = {c: 58.4, ok: true}; console.log(JSON.stringify([h.graphTarget(60, [-380, 400], f, 2, 6),'
              ' h.graphTarget(70, [-380, 400], f, 2, 6), h.graphTarget(-500, [-380, 400], f, 2, 6),'
              ' h.graphTarget(60, [-380, 400], {c: 58.4, ok: false}, 2, 6)]));')

    assert got == [58, 70, -380, 60]


def test_graph_top_starts_from_the_points_and_the_plateau():
    got = run('console.log(JSON.stringify([h.graphTop([], null, 4), h.graphTop([1, 2, 3, 4], null, 1),'
              ' h.graphTop([1], {P: 10}, 1)]));')

    assert got[0] == 4
    assert got[1] == pytest.approx(4.6)
    assert got[2] == pytest.approx(11)


def test_points_fade_from_green_to_dark_purple():
    got = run('console.log(JSON.stringify([h.fadeColor(0), h.fadeColor(1), h.fadeColor(2), h.fadeColor(9)]));')

    assert got[0] == 'rgb(74,222,128)'
    assert got[2] == got[3] == 'rgb(109,40,217)'
    assert got[1] not in (got[0], got[2])


def test_session_steps_with_and_without_a_motor():
    got = run('const s = o => h.sessionSteps(o).map(x => x.key + ":" + x.state).join(" ");'
              ' console.log(JSON.stringify([s({motor: true, tuning: true}), s({motor: true}),'
              ' s({motor: true, stars: true}), s({motor: true, stars: true, afRunning: true}),'
              ' s({motor: true, stars: true, afDone: true, checking: true}),'
              ' s({motor: true, stars: true, checking: true}), s({motor: false, stars: true}),'
              ' h.sessionSteps({motor: true}).map(x => x.label),'
              ' s({motor: true, preview: true, tuning: true}), s({motor: true, preview: true}),'
              ' s({motor: false, preview: true}), s({motor: true, preview: true, picking: true}),'
              ' s({motor: true, preview: true, stars: true})]));')

    assert got[0] == 'tune:current pick:todo autofocus:todo check:todo'
    assert got[1] == 'tune:done pick:current autofocus:todo check:todo'
    assert got[2] == 'tune:done pick:done autofocus:current check:todo'
    assert got[3] == 'tune:done pick:done autofocus:current check:todo'
    assert got[4] == 'tune:done pick:done autofocus:done check:current'
    assert got[5] == 'tune:done pick:done autofocus:skipped check:current'
    assert got[6] == 'tune:done pick:done hand:current'
    assert got[7] == ['Tune exposure', 'Pick stars', 'Autofocus', 'Check focus']
    # a preview stops after the tune; pressing Autofocus picks the stars and the usual steps follow
    assert got[8] == 'tune:current preview:todo'
    assert got[9] == 'tune:done preview:current'
    assert got[10] == 'tune:done preview-hand:current'
    assert got[11] == 'tune:done pick:current autofocus:todo check:todo'
    assert got[12] == 'tune:done pick:done autofocus:current check:todo'


def test_step_help_says_wait_or_press():
    got = run('console.log(JSON.stringify([h.stepHelp("tune", true), h.stepHelp("pick", true),'
              ' h.stepHelp("pick", false), h.stepHelp("autofocus", false), h.stepHelp("hand", false),'
              ' h.stepHelp("nope", false), h.stepHelp("preview", false), h.stepHelp("preview-hand", false)]));')

    assert got[0].startswith('Wait while the camera finds the exposure')
    assert got[1].startswith('Wait while the stars')
    assert got[2].startswith('The stars to measure are picked after the tune')
    assert got[3].startswith('Press Autofocus')
    assert got[4].startswith('Turn the focus ring')
    assert got[5] == ''
    assert 'Press Autofocus' in got[6] and 'Step the lens in or out' in got[6] and 'arrows' not in got[6]
    assert got[7].startswith('Turn the focus ring') and 'Autofocus' not in got[7]


def test_exit_buttons_hide_save_under_the_autofocus_save_and_cancel_shows_its_wait():
    got = run('var f = h.exitButtons; console.log(JSON.stringify([f(true, false, false, false),'
              ' f(true, true, false, false), f(true, false, true, false), f(true, false, false, true),'
              ' f(false, false, false, false)]));')
    plain, saved, busy, cancelling, watcher = got
    assert plain == {'save': {'hidden': False, 'disabled': False},
                     'cancel': {'disabled': False, 'busy': False, 'label': 'Cancel'}}
    assert saved['save']['hidden'] is True
    assert busy['save']['disabled'] is True and busy['cancel']['disabled'] is False
    assert cancelling['cancel'] == {'disabled': True, 'busy': True, 'label': 'Cancelling\u2026'}
    assert cancelling['save']['disabled'] is True
    assert watcher['save']['disabled'] is True and watcher['cancel']['disabled'] is True


def test_cancel_reasons_say_where_the_lens_is():
    got = run('console.log(JSON.stringify([h.endedText("cancelled"), h.endedText("cancel_short"),'
              ' h.endedText("done")]));')
    assert 'back where it was at Start' in got[0]
    assert 'could not get back' in got[1]
    assert got[2] == 'The focus session ended: the focus was saved.'


def test_step_bar_fills_with_the_tune_and_the_pick():
    got = run('const f = h.stepBar; console.log(JSON.stringify(['
              ' f({what: "tune", step: 1, of: 4, done: false}), f({what: "tune", step: 3, of: 4, done: false}),'
              ' f({what: "pick", frame: 2, of: 5, done: false}), f({what: "tune", done: true}),'
              ' f({what: "tune", message: "x", done: false}), f({what: "autofocus", step: 1, of: 2}),'
              ' f({what: "pick", frame: 9, of: 5, done: false})]));')
    # the tune's point N is being measured: N - 1 of them are done; a pick frame arrives once it is taken
    assert got == [0, 50, 40, None, None, None, 100]


def test_start_button_is_busy_until_capture_answers():
    out = run('var f = h.startButton;'
              ' console.log(JSON.stringify([f(true, false, false, "Start Live Preview"), f(true, true, true, "Start Live Preview"),'
              ' f(false, false, false, "Autofocus"), f(false, true, true, "Autofocus"),'
              ' f(true, true, false, "Autofocus")]));')
    assert out[0] == {'disabled': False, 'busy': False, 'label': 'Start Live Preview'}
    assert out[1] == {'disabled': True, 'busy': True, 'label': 'Starting\u2026'}
    assert out[2]['disabled'] is True and out[2]['busy'] is False
    assert out[3]['disabled'] is True
    assert out[4] == {'disabled': True, 'busy': False, 'label': 'Autofocus'}  # the other button waits, still


def test_step_labels_are_lens_degrees():
    # A 512-step motor through 82:12 gears turns the lens once in 3498.67 steps
    per = 512 * 82 / 12.0
    got = run('console.log(JSON.stringify([h.stepLabel("fine", 8, {0}), h.stepLabel("medium", 34, {0}),'
              ' h.stepLabel("coarse", 126, {0}), h.stepLabel("fine", 2, {0}), h.stepLabel("medium", null, null),'
              ' h.stepLabel("coarse", 10, 0)]));'.format(per))

    # without a lens message (or with no gearing) the fixed sizes stand in
    assert got == ['Fine · 0.8°', 'Medium · 3.5°', 'Coarse · 13°', 'Fine · 0.2°',
                   'Medium · 3.5°', 'Coarse · 13°']


def test_the_questions_say_what_each_answer_does():
    got = run('var f = h.confirmText; console.log(JSON.stringify([f("start", true), f("start", false),'
              ' f("start_af", true), f("again", true), f("cancel", true), f("cancel", false)]));')
    start, hand, start_af, again, cancel, cancel_hand = got

    assert start == {'t': 'Take over the camera?',
                     'b': 'Live Focus takes over the camera for a while, so sky pictures pause. When the session ends, '
                          'the camera goes back to how it is now. Cancel also brings the lens back to where it is now.',
                     'n': 'Not now', 'y': 'Start Live Preview', 'danger': False}
    assert 'lens' not in hand['b']  # a hand rig: nothing moves the lens
    assert start_af['b'] == start['b'] + ' Autofocus starts right away.'
    assert (start_af['n'], start_af['y']) == ('Not now', 'Autofocus')
    assert again == {'t': 'Autofocus again?', 'b': 'The lens leaves best focus and the scan starts over.',
                     'n': 'Keep focus', 'y': 'Autofocus', 'danger': False}
    assert cancel == {'t': 'End without saving?',
                      'b': 'The lens goes back to where it was at the start, and sky pictures resume.',
                      'n': 'Keep going', 'y': 'End session', 'danger': True}
    assert cancel_hand['b'] == 'Sky pictures resume.'


def test_autofocus_label_says_again_after_a_good_run():
    got = run('console.log(JSON.stringify([h.autofocusLabel(42.4, false), h.autofocusLabel(42.4, true),'
              ' h.autofocusLabel(null, true)]));')
    assert got == ['Autofocus · about 42 s', 'Autofocus again · about 42 s', 'Autofocus again']


def test_autofocus_rows_in_words():
    got = run('console.log(JSON.stringify([h.autofocusRows(null, "scan", 38), h.autofocusRows(null, "park", 1),'
              ' h.stageWords("fit"), h.stageWords("odd")]));')

    assert [(r['words'], r['state']) for r in got[0]] == [
        ('Moving to the start', 'done'), ('Scanning outward  (38 frames)', 'current'),
        ('Finding best focus', 'todo'), ('Moving to best focus', 'todo')]
    assert got[1][1]['words'] == 'Scanning outward  (1 frame)' and got[1][3]['state'] == 'current'
    assert got[2:] == ['Finding best focus', 'odd']


def test_seconds_left_counts_down_and_stops_at_zero():
    got = run('console.log(JSON.stringify([h.secondsLeft(100, 40, 110), h.secondsLeft(100, 40, 200),'
              ' h.secondsLeft(null, 40, 110)]));')

    assert got == [30, 0, None]


def test_pending_buttons_spin_until_capture_answers():
    got = run('let p = []; p = h.pendingAdd(p, 3, "motor", "b1"); p = h.pendingAdd(p, 4, "autofocus", "b2");'
              ' p = h.pendingAdd(p, null, "stop", "b2");'
              ' const a = h.pendingAnswered(p, 4); const b = h.pendingAnswered(p, 3);'
              ' console.log(JSON.stringify([h.pendingSpins(p, "b1"), a.map(x => x.kind), h.pendingSpins(b, "b1"),'
              ' b.length, h.pendingPicture(b).id, h.pendingDropKind(p, "stop").length]));')

    assert got == [True, ['motor', 'stop'], False, 3, 3, 2]


def test_the_tune_holds_the_lens_controls():
    got = run('console.log(JSON.stringify([h.tuneHoldsLens({tuning: true, searching: false}),'
              ' h.tuneHoldsLens({tuning: false, searching: true}), h.tuneHoldsLens({tuning: false, searching: false})]));')

    assert got == [True, True, False]


def test_save_waits_for_a_tune_or_a_pick():
    got = run('var f = h.stepRunning; console.log(JSON.stringify([f({tuning: true}), f({searching: true}),'
              ' f({picking: true}), f({tuning: false, searching: false, picking: false})]));')

    assert got == [True, True, True, False]
