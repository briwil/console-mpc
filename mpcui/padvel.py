"""A step laid down from the pads keeps how hard you hit the pad (the Move's pads aren't played the same way, so Console used the
default velocity, 100, for these):

    a drum step tapped with the SEQ pads            the step's velocity = the pad's
    a drum hit recorded live from the pads          the step it lands on gets the pad's velocity
    a drum step + a chromatic pad (pitch on a step) the step gets the pad's velocity
    a synth step tapped with the SEQ pads           its new notes get the pad's velocity

"The pad's velocity" is what Console plays: the PADS page's fixed velocity if it is on, else the hit through the curve."""

step = {}                      # step number 1-16 -> the velocity of its pad's last press
cur = [None]                   # while a pad is being handled: its velocity (for a live recording)
STEPS = range(16, 32)


def install(MoveBoard, MoveSeq, MoveSynth, Sequencer, pad_velocity):
    if pad_velocity is None:
        return
    orig_note, orig_pad = MoveBoard.note, MoveBoard.pad

    def note(self, num, val):
        if num in STEPS and val:
            try:
                step[num - 15] = pad_velocity(self.T, val)
            except Exception:
                pass
        return orig_note(self, num, val)
    MoveBoard.note = note

    def pad(self, p, vel):
        v = None
        if vel:
            try:
                v = pad_velocity(self.T, vel)
            except Exception:
                v = None
        cur[0] = v
        try:
            r = orig_pad(self, p, vel)
        finally:
            cur[0] = None
        try:                                                  # a held step + a chromatic pad: that note on the step
            T = self.T
            ms = T.mseq
            if v and p % 8 >= 4 and T.seq_page and ms.active() and ms.down and not ms.selected:
                e = T.engine
                lane = min(T.seqp.lane, e.drums.lanes - 1)
                with e.seq.lock:
                    for i in ms.down:
                        if i < e.seq.lane(lane).length:
                            e.seq.step(lane, i).vel = v
        except Exception:
            pass
        return r
    MoveBoard.pad = pad

    live = Sequencer.live_place

    def live_place(self, lane, tape_frame, frames_per_beat):
        i = live(self, lane, tape_frame, frames_per_beat)
        v = cur[0]
        if v:
            try:
                with self.lock:
                    self.lane(lane).steps[i].vel = v
            except Exception:
                pass
        return i
    Sequencer.live_place = live_place

    drum_step = MoveSeq.step

    def seq_step(self, n, down, shift=False):
        i, lane, before = None, None, False
        try:
            if down and not shift:
                i, lane = self.first() + n - 1, self.sp.lane
                before = bool(self.seq.step(lane, i).on) if i < self.seq.lane(lane).length else True
        except Exception:
            i = None
        r = drum_step(self, n, down, shift)
        try:
            v = step.get(n)
            if i is not None and v and not before and self.seq.step(lane, i).on:
                with self.seq.lock:
                    self.seq.step(lane, i).vel = v
                self.T.engine.seq_changed()
        except Exception:
            pass
        return r
    MoveSeq.step = seq_step

    synth_tap = MoveSynth._tap

    def tap(self, i):
        before = set()
        try:
            before = set(self.notes_at(i))
        except Exception:
            pass
        synth_tap(self, i)
        try:
            n = i - self.first() + 1
            v = step.get(n)
            if v:
                with self.seq.lock:
                    for note in set(self.notes_at(i)) - before:
                        self.seq.pattern.notes[i][note].vel = v
                self.T.engine.seq_changed()
        except Exception:
            pass
    MoveSynth._tap = tap
