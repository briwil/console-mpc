"""Shift and the knobs on the MPC, on an instrument's pages (its sound pages, LFO / INSERT / SENDS / PADS / ARP, its sequencer)
and the song insert pages:

    Shift + K1, K2, K3, FADER   knobs 5-8 (the MPC has four real knobs for the eight settings on a page)
    Shift + any other knob      the same as without Shift (no "one fine step at a time")

It works on the knob events before Console's handler sees them (so Console's own click counting, e.g. several clicks per
choice for DIST or CHOKE, counts the right knob). Other pages keep their Shift jobs: pan on the mixer and the tape page ..."""

SONG_INSERTS = ("song1", "song2")


def instrument_page(T, m):
    """An instrument's pages (not the tape, the mixer, the list, the song page, a menu), or a song insert page."""
    try:
        if m is not None and (m.open or m.kits.open):
            return False
        if T.fx_page:
            return T.fx_page in SONG_INSERTS
        if T.inst_page or getattr(T, "song_page", False):
            return False
        return bool((T.drum_page or T.seq_page) and T.engine and T.engine.drums)
    except Exception:
        return False


def remap(name, T, m):
    """The knob event as Console should see it."""
    if not (isinstance(name, tuple) and len(name) >= 4 and name[0] == "KNOB" and name[3] and 1 <= name[1] <= 8):
        return name
    if not instrument_page(T, m):
        return name
    n = name[1]
    if n <= 4 and not T.seq_page:                         # the sound pages: Shift + the four knobs = knobs 5-8
        n += 4
    return ("KNOB", n, name[2], False)


def wrap(handle):
    def wrapped(name, T, m, e):
        try:
            name = remap(name, T, m)
        except Exception:
            pass
        return handle(name, T, m, e)
    return wrapped
