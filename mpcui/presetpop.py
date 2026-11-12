"""The PRESETS page on the MPC: a box with the current preset; push the wheel and the list pops up.

    list closed      the wheel turns the pages, as on every other sound page; push opens the list
    list open        the wheel goes through the presets (each heard as you land on it); push keeps it and closes the
                     list; Back puts the sound you had back and closes it
    knob 1           the synth's bank (either way)

Console's own PRESETS page used the wheel for the list all the time, so the wheel couldn't leave the page."""

OPEN = [False]


def is_open():
    return OPEN[0]


def _on_page(T, m):
    try:
        if m.open or m.kits.open or T.fxpick.active or T.sbrowse.active:
            return False
        return bool(T.presets.on_page())
    except Exception:
        return False


def wrap(handle):
    def wrapped(name, T, m, e):
        try:
            if not _on_page(T, m):
                OPEN[0] = False
            else:
                pr = T.presets
                wheel = isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11
                if not OPEN[0]:
                    if wheel:                                    # the wheel: the pages (not the presets)
                        import knobgate
                        way = knobgate.gate(("wheel-pages",), name[2], False, 1)
                        if not way:
                            return
                        name = "RIGHT" if way > 0 else "LEFT"
                    elif name == "HOME":                         # push: the list
                        pr.sync()
                        OPEN[0] = True
                        return
                elif name == "HOME":                             # push: keep what you landed on
                    handle(name, T, m, e)
                    OPEN[0] = False
                    return
                elif name == "BACK":                             # back: the sound you had
                    if pr.orig is not None:
                        handle(name, T, m, e)
                    OPEN[0] = False
                    return
                elif not wheel and not (isinstance(name, tuple) and name[0] in ("KNOB", "TOUCH")):
                    OPEN[0] = False                              # any other button: the list goes (what you landed on stays)
        except Exception:
            import traceback
            print("presets list failed:\n" + traceback.format_exc(), flush=True)
        handle(name, T, m, e)
    return wrapped
