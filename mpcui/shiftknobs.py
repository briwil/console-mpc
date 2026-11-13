"""Shift + K1-K3 / FADER = knobs 5-8 on the sound pages (the drum / synth / instrument page and the insert pages).

The MPC has four real knobs for the 8 settings on those pages; with Shift held, the same four reach the next four. Shift is then used up,
so Console sees an ordinary turn of knob 5-8. Other pages (tape, mixer, sequencers, song ...) keep their own Shift jobs."""

INSERTS = ("insert", "insert2", "song1", "song2")


def on_sound_page(T):
    """The pages whose settings are knobs 1-8: an insert page, or the drum / synth sound page (no sequencer, list or other FX page on top)."""
    try:
        if T.fx_page:
            return T.fx_page in INSERTS
        if T.inst_page or T.seq_page:
            return False
        return bool(T.drum_page and T.engine and T.engine.drums)
    except Exception:
        return False


def install(Transport):
    orig = Transport.knob

    def knob(self, number, delta, shift):
        if shift and 1 <= number <= 4 and on_sound_page(self):
            return orig(self, number + 4, delta, False)
        return orig(self, number, delta, shift)
    Transport.knob = knob
