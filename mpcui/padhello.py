"""Start-up on the pads: Console's HELLO (letters sliding down 32 pads) needs the Move's pads. On the MPC every pad
just lights a random colour for 2 seconds (a new colour 4 times a second), then the pads go back to normal."""
import random
import time

COLOURS = [3, 11, 8, 15, 22, 16, 47]          # (orange, green, yellow, teal, purple, bright, pastel: Console's own colours)
SECONDS = 2.0
STEPS_PER_SECOND = 4

_start = [None]
_last = [None, None]                          # step number, the frame of that step


def hello_frame(now):
    """The 32 pad lights now (Console reads 32, the MPC shows 16 of them), or None once 2 seconds have gone by."""
    if _start[0] is None:
        _start[0] = now
    t = now - _start[0]
    if t >= SECONDS:
        return None
    k = int(t * STEPS_PER_SECOND)
    if _last[0] != k:
        _last[0], _last[1] = k, [random.choice(COLOURS) for _ in range(32)]
    return list(_last[1])


def install(main_globals):
    main_globals["hello_frame"] = hello_frame
