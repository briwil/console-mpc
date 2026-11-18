"""Step entry on the drum sequencer page (MPC only): turn the wheel and a box (the cursor) appears on the steps; the wheel
moves it along the lane and a push puts the selected drum's step there (again: takes it off). Shift + push selects the step for
its settings. The pads only play / pick the drums (SEQ RECORD, in the bridge, turns them into the 16 steps).
Installed over Console's MoveBoard by mpc_app.py; Console's own files are not changed."""
import time

WHEEL = 14
PUSH = 3                                                         # the wheel's push (the MPC encoder push)
BACK = 51
REDO, LOOPMARK, ARMSEL, TRIPLETS, METRO = 104, 105, 106, 107, 108
INSTHOME, SETTINGSKEY = 112, 113                                  # SAMPLE (page 1 of the instrument) and Shift + SAMPLE (SETTINGS), bridge/mapping.h
PROJECT, SONGPAGE, GRIDNEXT = 109, 110, 111                     # Shift + pad 16 / 12 / 14 on the tape-style pages (as printed on the pads)
ERASE = 119                          # private CCs from the bridge: REDO, set a loop point, arm / disarm the selected track
K1 = 71                                                          # Move knob 1 (relative clicks)
ARPPOP = 114                                                      # NOTE REPEAT: the ARP pop-up (bridge/mapping.h)
K1_ABS = 115                                                     # K1's absolute position from the bridge (0-127). (Not 112: SAMPLE; not 118: CHOP = SPLICE)
MAX_LEN = 64


def length_page(T):
    """K1 sets a length: a drum lane's, or the synth pattern's (or the picked note's), no steps selected or held."""
    if getattr(T, "arp_pop", 0) or getattr(T, "pads_pop", 0):
        return False
    try:
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False
        if not T.seq_page or T.fx_page or T.punch.active() or T.auto.active() or not T.engine:
            return False
        if T.synth_shown():
            ms = T.msyn
            return bool(ms.active() and not ms.selected and not ms.down and not (ms.kind and ms.lane is None))
        ms = T.mseq
        return bool(ms.active() and ms.held is None and not ms.selected and T.engine.drums is not None)
    except Exception:
        return False


def set_length(T, val):
    """Length from K1's position: 0 -> 1 step, 127 -> 64."""
    target = 1 + int(round(val * (MAX_LEN - 1) / 127.0))
    if T.synth_shown():
        ms = T.msyn
        cur = ms.length()
        if target != cur:
            ms.knob(1, target - cur, False)
    else:
        ms = T.mseq
        cur = T.engine.seq.lane(T.seqp.lane).length
        if target != cur:
            ms.knob(1, target - cur, False)



def active(T):
    """Drum sequencer page, nothing selected, no popups on top: the cursor is in use."""
    try:
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False                                    # a menu (SAVE PRESET ...) is up: the wheel and push are the menu's
        ms = T.mseq
        if not T.seq_page or T.fx_page or not ms.active() or ms.held is not None:
            return False
        if T.punch.active() or T.auto.active() or T.synth_shown():
            return False
        return T.engine is not None and T.engine.drums is not None
    except Exception:
        return False


def in_synth_seq(T):
    """A synth's sequencer page (steps selected or not, no menu or pop-up on top): the wheel's white box and push are in use."""
    try:
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False
        if getattr(T, "arp_pop", 0) or getattr(T, "pads_pop", 0):
            return False
        if not T.seq_page or T.fx_page or T.punch.active() or T.auto.active() or T.sbrowse.active:
            return False
        return bool(T.engine and T.msyn.active())
    except Exception:
        return False


def synth_move(T, way):
    """The synth sequencer's wheel: the white box along the steps (the first turn only brings it up); the 16 steps shown follow it."""
    import sequencer
    ms = T.msyn
    length = ms.length()
    if not getattr(ms, "cur_on", False):
        ms.cur_on = True
        ms.cur = min(_cursor(ms), max(0, length - 1))
        ms.page = ms.cur // 16
        return
    d = 1 if way > 0 else -1
    cur = _cursor(ms)
    nxt = cur + d
    while 0 <= nxt < length and sequencer.dark(nxt, sequencer.TRIPLETS):
        nxt += d
    if 0 <= nxt < length:
        cur = nxt
    ms.cur = cur
    ms.page = cur // 16


def synth_click(T):
    """The wheel was pushed on a synth sequencer: an empty step gets a note; a step with notes joins the selected steps (pushed again: leaves)."""
    import sequencer
    ms = T.msyn
    if not getattr(ms, "cur_on", False):
        return
    i = _cursor(ms)
    if i >= ms.length():
        T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, ms.length()), 2)
        return
    if sequencer.dark(i, sequencer.TRIPLETS):
        return
    if i in ms.selected:
        ms.selected.remove(i)
        ms.sel = None
        return
    here = ms.notes_at(i)
    on = (ms.lane in here) if (ms.lane is not None and ms.kind) else bool(here)
    if not on:
        ms._tap(i)                                              # an empty step: the notes you're holding (or the last / first one) go down
        return
    if not ms.selected:
        ms.knob_page = getattr(T, "drum_tab", 0)
    ms.selected = list(ms.selected) + [i]
    ms.sel = None


def on_tape(T):
    """The 8-track page (not zoomed, no menu on top)."""
    try:
        import native
        return bool(T.engine) and T.focus.track is None and native.on_tape_page(T, getattr(T, "_mpc_menu", None))
    except Exception:
        return False


def pos_text(T):
    try:
        return T.position_text(T.tape.pos)
    except Exception:
        return ""


def loop_mark(T):
    """Shift + LOOP: the first press marks a point (the loop is there, four bars long, until you mark the other one), the second sets the
    other end: whichever is earlier is the IN point, the later the OUT point. Both at the same spot: the points are taken away."""
    e = T.engine
    here = T.tape.pos
    mark = getattr(T, "_loop_mark", None)
    if mark is None:
        T._loop_mark = here
        e.set_loop_point("in", here)
        T.say("LOOP POINT 1 AT %s  (SHIFT + LOOP AGAIN FOR THE OTHER)" % pos_text(T), 4)
        return
    T._loop_mark = None
    a, b = (mark, here) if mark <= here else (here, mark)
    if abs(b - a) < 1e-6:
        e.clear_region()
        T.say("IN / OUT POINTS CLEARED", 2)
        return
    e.set_region(a, b, True)
    T.say("LOOP ON: IN %s  OUT %s" % (T.position_text(a), T.position_text(b)), 3)


def tape_button(board, num):
    T = board.T
    e = T.engine
    if not e:
        return
    if num == REDO:
        try:
            seqish = T.seq_page and not (T.fx_page or T.punch.active() or T.auto.active())
        except Exception:
            seqish = False
        if seqish:                                              # Shift + PLUS on a sequencer page: the pattern's redo
            sp = T.sp()
            n = sp.seq.redo() if hasattr(sp.seq, "redo") else None      # (never crash the app over a redo)
            if n is None:
                T.say("NOTHING TO REDO", 2)
            else:
                sp._gesture = None
                e.seq_changed()
                T.say("REDONE%s" % ("" if n == sp.seq.current else " IN PATTERN %d" % (n + 1)), 2)
            return
        T.say("REDONE" if e.redo() else "NOTHING TO REDO", 2)
    elif num == LOOPMARK:
        loop_mark(T)
    elif num == ARMSEL:
        board.keys.put("ARM%d" % T.armed)
    elif num == TRIPLETS:
        e.set_triplets(not e.triplets)
        T.say("TRIPLETS ON  (STEPS 4, 8, 12, 16 OFF)" if e.triplets else "TRIPLETS OFF", 3)
    elif num == METRO:
        import metronome
        metronome.toggle(T)


def in_seq(T):
    """Drum sequencer page (steps selected or not): the wheel's box and push are in use."""
    try:
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False
        ms = T.mseq
        if not T.seq_page or T.fx_page or not ms.active():
            return False
        if T.punch.active() or T.auto.active() or T.synth_shown():
            return False
        if T.engine is None or T.engine.drums is None:
            return False
        return hasattr(T.engine.seq, "lane")                    # (a synth's NoteSequencer has no drum lanes: not this page)
    except Exception:
        return False


def click(T, shift):
    """The wheel was pushed. On an empty step: the selected drum's step goes down. On a step that is on: it joins the selected
    steps (they blink and the pads become their settings); pushed again on a selected step: it leaves them. Shift + push does the
    same. ERASE takes steps off (see erase)."""
    import sequencer
    ms, e, sp = T.mseq, T.engine, T.seqp
    lane = sp.lane
    length = e.seq.lane(lane).length
    if not getattr(ms, "cur_on", False) and not ms.selected:
        return                                                   # no box yet: turn the wheel first
    i = _cursor(ms)
    if i >= length:
        T.say("STEP %d IS PAST THE END (LENGTH %d: KNOB 1)" % (i + 1, length), 2)
        return
    if sequencer.dark(i, sequencer.TRIPLETS):
        return
    on = bool(e.seq.step(lane, i).on)
    if not on:                                                   # an empty step: put it down
        sp._edit(("toggle", time.monotonic()))
        with e.seq.lock:
            e.seq.step(lane, i).on = True
        e.seq_changed()
        return
    if i in ms.selected:                                         # already selected: it leaves the selection
        ms.selected.remove(i)
        ms.sel = None
        return
    if not ms.selected:
        ms.knob_page = getattr(T, "drum_tab", 0)                 # (the knobs start on the sound page you were on)
    ms.selected = list(ms.selected) + [i]                        # one more selected step (BACK: none)
    ms.sel = None


def erase(T):
    """ERASE on the drum sequencer page: the selected steps come off; none selected: the step under the box."""
    ms, e, sp = T.mseq, T.engine, T.seqp
    lane = sp.lane
    length = e.seq.lane(lane).length
    which = [i for i in ms.selected if i < length]
    if not which:
        if not getattr(ms, "cur_on", False):
            return
        which = [_cursor(ms)]
    which = [i for i in which if i < length and e.seq.step(lane, i).on]
    ms.selected, ms.sel = [], None
    if not which:
        return
    sp._edit(("toggle", time.monotonic()))                       # (undo works as for a step button)
    with e.seq.lock:
        for i in which:
            e.seq.step(lane, i).on = False
    e.seq_changed()


def deselect(T):
    """Off the sequencer pages: no steps stay selected (called every frame by the screen)."""
    try:
        if T.seq_page:
            return
        for ms in (T.mseq, T.msyn):
            if getattr(ms, "selected", None):
                ms.selected = []
                if hasattr(ms, "sel"):
                    ms.sel = None
    except Exception:
        pass


def _cursor(ms):
    c = getattr(ms, "cur", 0)
    return c if isinstance(c, int) and c >= 0 else 0


def move(T, way):
    ms, sp, e = T.mseq, T.seqp, T.engine
    lane = sp.lane
    length = e.seq.lane(lane).length
    import sequencer
    if not getattr(ms, "cur_on", False):
        ms.cur_on = True                                         # the first turn only brings the box up
        ms.cur = min(_cursor(ms), max(0, length - 1))
        ms.page[lane] = ms.cur // 16
        return
    d = 1 if way > 0 else -1
    cur = _cursor(ms)
    nxt = cur + d
    while 0 <= nxt < length and sequencer.dark(nxt, sequencer.TRIPLETS):
        nxt += d                                                 # triplets: the dark steps (every 4th) don't play, the box skips them
    if 0 <= nxt < length:
        cur = nxt
    ms.cur = cur
    ms.page[lane] = cur // 16                                    # the 16 steps shown follow the box


def lay(T, p, vel=None):
    """A drum pad (Move pad number p) was hit while stopped: its step on the cursor's step is switched on (off if it was on)."""
    ms, sp, e = T.mseq, T.seqp, T.engine
    d = e.drums
    r, c = divmod(p, 8)
    if c >= 4:
        return
    lane = r * 4 + c
    if lane >= d.lanes:
        return
    cur = _cursor(ms)
    if cur >= e.seq.lane(lane).length:
        return
    sp._edit(("toggle", time.monotonic()))                       # (undo works as for a step button)
    with e.seq.lock:
        st = e.seq.step(lane, cur)
        st.on = not st.on                                        # a hit on a step that has one takes it off
        if st.on and vel:
            st.vel = max(1, min(127, int(vel)))                  # a new step takes the velocity you hit with
    e.seq_changed()
    ms.page[lane] = cur // 16


def arp_popup_toggle(T):
    """NOTE REPEAT: the ARP as a pop-up over the page you are on (a synth's sound or sequencer pages). Again closes it."""
    if getattr(T, "arp_pop", 0):
        T.arp_pop = 0
        return
    ok = bool(T.engine and T.synth_shown() and (T.drum_page or T.seq_page)
              and not (T.fx_page or T.inst_page or T.song_page or T.auto_page or T.punch.active() or T.sbrowse.active))
    if not ok:
        T.say("THE ARP IS FOR SYNTHS", 2)
        return
    T.arp_pop = 1


def auto_value_page(T):
    try:
        return bool(T.auto.active() and T.auto.mode == "edit" and not getattr(T, "arp_pop", 0) and not getattr(T, "pads_pop", 0))
    except Exception:                                          # noqa: BLE001
        return False


def focus_view(T):
    """The tape's zoomed track view (no menu or other page on top)."""
    try:
        if not T.engine or T.focus.track is None:
            return False
        if T.fx_page or T.seq_page or T.drum_page or T.inst_page or getattr(T, "song_page", False):
            return False
        mn = getattr(T, "_mpc_menu", None)
        return not (mn is not None and (mn.open or mn.kits.open))
    except Exception:                                                            # noqa: BLE001
        return False


def focus_input(T, side, val):
    """K2 (side 0) / K3 (side 1) in the zoomed view: the pot's position picks the input, evenly spaced."""
    e, n = T.engine, T.focus.shown
    t = n - 1
    if T.recording:
        return
    if side == 1 and t not in e.stereo:
        return                                                                   # (a mono track: K3 does nothing)
    text = e.place_input(t, side, val / 127.0)
    if text is not None:
        T.say("TRACK %d%s  INPUT %s" % (n, " STEREO" if t in e.stereo else "", text), 2)
        T.input_popup = (time.monotonic() + 2.5, t, side)


def sound_k1(T, n=1):
    """On a sound page: the n-th setting on the page (knob n's), or None when that knob isn't a number there."""
    try:
        if not T.drum_page or T.seq_page or T.fx_page or T.inst_page or T.song_page or T.sbrowse.active or not T.engine:
            return None
        if T.punch.active() or T.auto.active() or T.mlfo.active() or T.engine.drums is None:
            return None
        if getattr(T, "arp_pop", 0) or getattr(T, "pads_pop", 0):
            return None
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return None
        if getattr(T, "presets", None) is not None and T.presets.on_page():
            return None
        pages = T.drum_pages()
        params = pages[min(T.drum_tab, len(pages) - 1)][1]
        if len(params) < n:
            return None
        d = T.engine.drums
        if d.kind(params[n - 1]) in ("menu", "onoff"):
            return None
        return params[n - 1]
    except Exception:                                                            # noqa: BLE001
        return None


def sound_k1_set(T, val, n=1):
    """K1-K3 are pots: the position (0-127) is the setting's place from its lowest value to its highest."""
    param = sound_k1(T, n)
    if param is None:
        return False
    e = T.engine
    top = e.drums.stepped(param, 0, 100000)
    e.drums.set_param(param, int(round(val / 127.0 * top)))
    with e.lock:
        e.dirty.add(-1)
    try:
        import time as _t
        T.drumpage.edited[n] = _t.monotonic()
    except Exception:                                                            # noqa: BLE001
        pass
    return True


def step_setting_end(T, val):
    """Steps selected and a setting picked, knob 1 turning it by clicks: when the pot reaches an end stop the setting goes to its
    lowest (or highest) value, so all the way round always means the end, however the clicks added up. True when it did."""
    last = getattr(T, "_k1_end_last", 64)
    T._k1_end_last = val
    way = -1 if (val <= 1 and last > 1) else 1 if (val >= 126 and last < 126) else 0
    if not way:
        return False
    try:
        if T.fx_page or T.punch.active() or T.auto.active() or not T.seq_page or not T.engine:
            return False
        ms = T.msyn if T.synth_shown() else T.mseq
        if not (ms.active() and ms.selected and ms.sel is not None):
            return False
        for _ in range(64):                                     # (a setting that steps through choices moves one a call)
            ms.set_selected(way * 64, True)
    except Exception:                                           # noqa: BLE001
        return False
    return True


def swap_plus_minus(board, num, val, orig_cc):
    """On a sequencer page: MINUS / PLUS = Undo / Redo, and Shift + MINUS / PLUS = the steps' previous / next page (the bridge sends them the
    other way round: its arrows plain, undo / redo with Shift). Not in the pop-ups (they use PLUS / MINUS themselves)."""
    T = board.T
    try:
        if not T.seq_page or T.fx_page or T.inst_page or T.song_page or T.sbrowse.active:
            return False
        if getattr(T, "arp_pop", 0) or getattr(T, "pads_pop", 0):
            return False
        mn = getattr(T, "_mpc_menu", None)
        if mn is not None and (mn.open or mn.kits.open):
            return False
    except Exception:                                                            # noqa: BLE001
        return False
    if num in (62, 63) and not board.shift:                                      # MINUS / PLUS plain: Undo / Redo
        if val:
            if num == 62:
                board.keys.put("UNDO")
            else:
                tape_button(board, REDO)
        return True
    if num in (56, REDO) and board.shift:                                        # Shift + MINUS / PLUS (the bridge's undo / redo): the page of steps
        sh, board.shift = board.shift, False
        try:
            orig_cc(board, 62 if num == 56 else 63, val)
        finally:
            board.shift = sh
        return True
    return False


def pads_popup_toggle(T):
    """PAD FX: the PADS settings (key, scale, octave, velocity, curve) as a pop-up over the page you are on. Again closes it."""
    if getattr(T, "pads_pop", 0):
        T.pads_pop = 0
        return
    ok = bool(T.engine and T.engine.drums and T.engine.slot is not None and (T.drum_page or T.seq_page)
              and not (T.fx_page or T.inst_page or T.song_page or T.auto_page or T.punch.active() or T.sbrowse.active))
    if ok:
        T.pads_pop = 1


def _lp_fire(board, name):
    T = board.T
    board.keys.put(("BTN", name))


def _lp_tick(board):
    """Every frame: a B button held 0.6 s fires its menu; the CHANGE / REMOVE request waits for the instruments page."""
    T, now = board.T, time.monotonic()
    for num, ent in list(T.__dict__.get("bpress", {}).items()):
        if not ent[1] and now - ent[0] >= 0.6:
            ent[1] = True
            _lp_fire(board, {43: "SETTINGS", 41: "FILE", 40: "INST_MENU"}[num])
    w = T.__dict__.get("want_inst_menu", 0)
    if w:
        if T.inst_page and not T.fx_page and T.instp.mode is None:
            T.want_inst_menu = 0
            T.instp.shift_push()
        elif now > w:
            T.want_inst_menu = 0


def install(MoveBoard, pad_velocity=None):
    orig_cc, orig_pad, orig_note = MoveBoard.cc, MoveBoard.pad, MoveBoard.note

    def cc(self, num, val):
        T = self.T
        if val and num in (43, 41, 40):                                         # B1 / B2 / B3: the start-up animation goes away (native.py)
            try:
                import native
                native.intro_dismiss()
            except Exception:                                                   # noqa: BLE001
                pass
        if num in (43, 41, 40):                                                 # B1 / B2 / B3: Shift or a long press = SETTINGS / PROJECT / CHANGE-REMOVE
            lp = {43: "SETTINGS", 41: "FILE", 40: "INST_MENU"}[num]
            bp = T.__dict__.setdefault("bpress", {})
            if T.__dict__.get("lp_tick") is None:
                T.lp_tick = lambda: _lp_tick(self)
            if val and self.shift:
                bp.pop(num, None)
                _lp_fire(self, lp)
                return
            if val:
                bp[num] = [time.monotonic(), False]
                return
            ent = bp.pop(num, None)
            if ent is not None and not ent[1]:
                self.keys.put(("BTN", {43: "DRUMS", 41: "FX", 40: "TAPE"}[num]))   # (a short press: the button's own action, now)
            return
        if num == 101:                                                          # the song page: SEQ = the instrument's sequencer (bridge/mapping.h)
            if val:
                self.keys.put("SEQ_PAGE")
            return
        if num == 103:                                                          # the song page, pad 12 held: the wheel's clicks = PLAYS
            self.keys.put(("PLAYS", 1 if val < 64 else -1))
            return
        if num == 120:                                                          # pad 12 held / let go
            T.plays_held = time.monotonic() + 3600 if val else 0.0
            return
        if num == 102:                                                          # what the pads are now (bridge/mapping.h): named for a second
            try:
                if not on_tape(T) and not T.inst_page and not T.song_page:
                    T.pad_label = (time.monotonic() + 1.0, {1: "PADS", 2: "KNOB FX", 3: "SEQ", 4: "STEP SETTINGS"}.get(val, ""))   # (a pop-up in the middle of the screen: native.py)
            except Exception:                                                   # noqa: BLE001
                pass
            return
        if num == ARPPOP and getattr(T, "pads_pop", 0):
            return                                                              # (the PADS pop-up is up: close it first)
        if num == ARPPOP:                                                       # NOTE REPEAT: the ARP pop-up, on / off
            if val:
                arp_popup_toggle(T)
            return
        if (getattr(T, "arp_pop", 0) or getattr(T, "pads_pop", 0)) and num in (REDO, LOOPMARK, ARMSEL, TRIPLETS, METRO, INSTHOME, SETTINGSKEY, PROJECT,
                                                SONGPAGE, GRIDNEXT, ERASE, WHEEL, K1_ABS, PUSH):
            return                                                              # (the pop-up: only the ARP's own controls work)
        if swap_plus_minus(self, num, val, orig_cc):
            return
        if num in (REDO, LOOPMARK, ARMSEL, TRIPLETS, METRO):                    # the bridge's tape-page buttons (see bridge/mapping.h)
            if val:
                tape_button(self, num)
            return
        if num in (INSTHOME, SETTINGSKEY):
            if val:
                self.keys.put("INST_HOME" if num == INSTHOME else "SETTINGS")
            return
        if num == PUSH and T.inst_page and not T.fx_page and not self.shift:
            # the INSTRUMENTS page, a loaded slot: a short push opens it as always; holding the push for a moment (instpage.tick)
            # opens CHANGE / REMOVE, like Shift + push
            ip, e_ = T.instp, T.engine
            if val:
                if ip.mode is None and e_ and e_.drums and e_.slots[ip.row]:
                    ip.push_down, ip.push_fired = time.monotonic(), False
                    return
            elif getattr(ip, "push_down", None) is not None:
                fired = ip.push_fired
                ip.push_down = None
                if not fired:
                    orig_cc(self, PUSH, 127)                                    # (it was a short push: it happens now)
                    orig_cc(self, PUSH, 0)
                return
        if num in (PROJECT, SONGPAGE, GRIDNEXT):                                # Shift + pad 16 / 12 / 14 (bridge/mapping.h)
            if val:
                self.keys.put("FILE" if num == PROJECT else "SONG" if num == SONGPAGE else ("KNOB", 10, 1, False))
            return
        if num == ERASE and not self.shift and (in_seq(T) or getattr(self, "_erase_seq", False)):
            self._erase_seq = bool(val)                                         # (its release is swallowed too)
            if val:
                erase(T)
            return
        if on_tape(T) and (num in (115, 116, 122) or 71 <= num <= 74):
            # the tape page: K1 and the FADER are pots, their position is the selected track's volume (0-100 %, end to end); K2 is its
            # pan (left end L100, middle centre, right end R100). Their clicks are not used here (the position was).
            if num in (115, 122, 116) and T.engine:
                e, tr = T.engine, T.armed
                if num == 116:
                    target = val / 127.0 * 2.0 - 1.0
                    target = 0.0 if abs(target) < 0.04 else target
                    T.pan(tr, target - e.pans[tr - 1])
                else:
                    T.volume(tr, round(val / 127.0, 3) - e.volumes[tr - 1])
            return
        if num in (116, 117) and focus_view(T):                                  # the zoomed track: K2 / K3 are pots, the position picks the input
            T._pot_abs_at = getattr(T, "_pot_abs_at", {})
            T._pot_abs_at[num - 44] = time.monotonic()
            focus_input(T, num - 116, val)
            return
        if num in (72, 73) and val and focus_view(T) and time.monotonic() - getattr(T, "_pot_abs_at", {}).get(num, -9.0) < 0.15:
            return                                              # (its clicks are not used there: the position was)
        if num in (K1_ABS, 116, 117) and sound_k1_set(self.T, val, {K1_ABS: 1, 116: 2, 117: 3}[num]):
            self.T._pot_abs_at = getattr(self.T, "_pot_abs_at", {})
            self.T._pot_abs_at[{K1_ABS: 71, 116: 72, 117: 73}[num]] = time.monotonic()
            self.T._k1_abs_at = time.monotonic() if num == K1_ABS else getattr(self.T, "_k1_abs_at", -9.0)
            return                                              # (a sound page: a pot's position is the setting, end to end)
        if num in (71, 72, 73) and val and time.monotonic() - getattr(self.T, "_pot_abs_at", {}).get(num, -9.0) < 0.15 \
                and sound_k1(self.T, num - 70) is not None:
            return                                              # (its clicks are not used there: the position was)
        if num in (116, 117):
            return                                              # (K2 / K3's positions: only used on the pages above)
        if (num == K1_ABS or num == K1) and auto_value_page(T):
            now = time.monotonic()
            if num == K1_ABS:
                T._k1_abs_at = now
                T.auto.abs_knob(val)                           # AUTOMATION pop-up: K1 is a pot, its position is the value
            elif val and now - getattr(T, "_k1_abs_at", -9.0) > 0.15:
                T.auto.knob(1, val - 128 if val > 63 else val, False)     # (clicks with no pot before them: the wheel in KNOB FX as knob 1)
            return
        if num == K1_ABS and step_setting_end(T, val):
            return                                              # (the pot at an end stop: the selected step setting goes to its end)
        if num == K1_ABS or num == K1:
            if length_page(T):
                now = time.monotonic()
                if num == K1_ABS:
                    T._k1_abs_at = now
                    set_length(T, val)                          # K1 is a pot: its position IS the length (1-64)
                elif val and now - getattr(T, "_k1_abs_at", -9.0) > 0.15:
                    # clicks with no pot position before them: the wheel in KNOB FX mode (pad 1 held) acting as knob 1
                    step = val - 128 if val > 63 else val
                    step = 1 if step > 0 else -1
                    last_t, last_way = getattr(T, "_len_wheel", (-9.0, 0))
                    if now - last_t < 0.02 and step == last_way:
                        return                                  # (the bridge sends a notch of the wheel as 4 clicks: a length moves one a notch)
                    T._len_wheel = (now, step)
                    if T.synth_shown():
                        T.msyn.knob(1, step, False)
                    else:
                        T.mseq.knob(1, step, True)              # (True: no speeding up, one a notch)
                return                                          # (the pot's own clicks are not used there)
            if num == K1_ABS:
                return
        if num == WHEEL and val and self.shift and on_tape(T):
            step = val - 128 if val > 63 else val
            if step:
                self.keys.put(("KNOB", 10, 1 if step > 0 else -1, False))   # Shift + wheel on the tape page: the grid (all 8 tracks show, nothing scrolls)
            return
        if num == PUSH and val and (on_tape(T) or focus_view(T)):
            self.keys.put("HOME" if self.shift else "SPLICE")   # the tape page: push the wheel = SPLICE (like CHOP); Shift + push = the playhead to the start / loop in
            return
        if num == PUSH and val and in_seq(T):
            click(T, self.shift)
            return
        if num == PUSH and val and in_synth_seq(T):
            synth_click(T)
            return
        if num == BACK and val and not self.shift and in_seq(T) and T.mseq.selected:
            T.mseq.selected, T.mseq.sel = [], None               # BACK: done with the selected steps
            return
        if num == WHEEL and val and not self.shift and in_seq(T) and T.mseq.selected and T.mseq.sel is None:
            step = val - 128 if val > 63 else val
            if step:
                move(T, step)                                    # (the box keeps moving; K1 is the amount)
            return
        if num == WHEEL and val and not self.shift and in_synth_seq(T) and T.msyn.sel is None and (T.msyn.selected or not T.engine.playing):
            step = val - 128 if val > 63 else val
            if step:
                synth_move(T, step)                              # (steps selected: the box keeps moving too)
            return
        if num == WHEEL and val and not self.shift and active(self.T) and not self.T.engine.playing:
            step = val - 128 if val > 63 else val
            if step:
                move(self.T, step)
            return
        orig_cc(self, num, val)

    def note(self, num, val):
        T = self.T
        if num == 17 and val and self.shift and not getattr(T, "arp_pop", 0) and not T.inst_page and not T.fx_page:
            pads_popup_toggle(T)                                 # PAD FX (Shift + step 2): the PADS pop-up
            if getattr(T, "pads_pop", 0) or T.drum_page or T.seq_page:
                return
        if (num in (17, 18) and val and self.shift and T.seq_page and T.drum_page
                and not (T.punch.active() or T.auto.active() or T.fx_page or T.inst_page or T.song_page or T.sbrowse.active)
                and (T.synth_shown() or num == 17)):
            # NOTE REPEAT / PAD FX from inside a sequencer: out to the sound page first, then on to the arp / pads page
            T.punch.leave()
            T.auto_page = T.seq_page = False
            T.seqp.held, T.synthp.held = {}, {}
            T.mlfo.tab = None
            T._from_seq = "pending"                         # (the page opens next; closing it goes back to the sequencer)
        orig_note(self, num, val)

    def pad(self, p, vel):
        orig_pad(self, p, vel)                                   # the pads play and pick the drums; they never lay steps here

    MoveBoard.cc, MoveBoard.pad, MoveBoard.note = cc, pad, note
    try:                                                         # the arp / pads page opened from a sequencer: its icon again goes back there
        import movelfo
        for name in ("goto_arp", "goto_pads"):
            orig = getattr(movelfo.MoveLFO, name)

            def wrapped(self, _orig=orig):
                T = self.T
                was_open = self.tab is not None
                _orig(self)
                state = getattr(T, "_from_seq", None)
                if not was_open and self.tab is not None:
                    T._from_seq = "armed" if state == "pending" else None
                elif was_open and self.tab is None and state == "armed":
                    T._from_seq = None
                    T.seq_page = True
                elif was_open:
                    T._from_seq = None
            setattr(movelfo.MoveLFO, name, wrapped)
    except Exception:
        import traceback
        print("arp / pads return failed:\n" + traceback.format_exc(), flush=True)
