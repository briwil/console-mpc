"""Settings that pick a mode (DIST, CHOKE, a wave, on / off...) instead of a number: one click of a knob is
too touchy there, so it takes CLICKS clicks the same way to move to the next choice. Turning the other way,
or pausing, starts the count again. Shift + turn moves one choice a click."""
import time

CLICKS = 5
PAUSE = 0.7                       # seconds without a click: the count starts again

_acc = {}


def gate(key, delta, shift=False, clicks=None):
    """The clicks to apply now: 0 until enough have come, then 1 or -1. Without `clicks`: one more than the
    knob speed (SPEED), so the one setting (Shift + the volume knob) makes every knob less or more touchy."""
    if clicks is None:
        clicks = SPEED + 1
    if shift:
        return 1 if delta > 0 else -1
    now = time.monotonic()
    total, last = _acc.get(key, (0, 0.0))
    if now - last > PAUSE or (total and (total > 0) != (delta > 0)):
        total = 0
    total += 1 if delta > 0 else -1
    if abs(total) >= clicks:
        _acc[key] = (0, now)
        return 1 if total > 0 else -1
    _acc[key] = (total, now)
    return 0


def is_choice(drums, param):
    if param in getattr(drums, "fast_params", ()):        # a long list (the sampler's files): not a mode
        return False
    try:
        return drums.kind(param) in ("menu", "onoff")
    except Exception:
        return False


# ---------------------------------------------------------------- the global knob speed
# Every knob (1-8) that changes a number takes SPEED clicks of the encoder per step: one value for all of
# them, kept in console/knob-sensitivity. Shift + the volume knob on the Move changes it.
SPEED = 4
MIN_SPEED, MAX_SPEED = 1, 12
_path = None


def load(path):
    global SPEED, _path
    _path = path
    try:
        SPEED = max(MIN_SPEED, min(MAX_SPEED, int(float(open(path).read().strip()))))
    except (OSError, ValueError):
        pass


def set_speed(value):
    global SPEED
    SPEED = max(MIN_SPEED, min(MAX_SPEED, int(value)))
    if _path:
        try:
            with open(_path, "w") as f:
                f.write(str(SPEED))
        except OSError:
            pass
    return SPEED


def numeric(key, delta):
    """A number knob: the clicks to apply now (0 until SPEED clicks have come the same way)."""
    now = time.monotonic()
    total, last = _acc.get(key, (0, 0.0))
    if now - last > PAUSE or (total and (total > 0) != (delta > 0)):
        total = 0
    total += delta
    n = int(abs(total) // SPEED)
    if n:
        total -= (1 if total > 0 else -1) * n * SPEED
    _acc[key] = (total, now)
    return n if delta > 0 else -n
