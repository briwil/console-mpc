"""Shift + STOP on the MPC: a small menu instead of quitting at once.

    BACK TO MPC OS    save, quit Console, the stock MPC app starts (what Shift + STOP did before)
    SHUT DOWN         save, quit Console, switch the Sample off
    CANCEL            carry on

    wheel: choose   push the wheel: do it   STOP / Back: cancel   (Shift + STOP again also cancels)
Every other control is ignored while it is up."""
import os

OPEN = [False]
CHOICE = [0]
ACTION = [None]                       # "stock" or "shutdown", once chosen
ITEMS = ("BACK TO MPC OS", "SHUT DOWN", "CANCEL")
SHUTDOWN_FLAG = "/data/UserData/console/SHUTDOWN"


def is_open():
    return OPEN[0]


def hook(name):
    """Called for every key before Console sees it. Returns "pass" (not ours), "eat" (dealt with) or "quit" (leave Console)."""
    if not OPEN[0]:
        if name == "QUIT":
            OPEN[0] = True
            CHOICE[0] = 0
            return "eat"
        return "pass"
    if name == "QUIT" or name == "BACK" or name == "STOP":
        OPEN[0] = False
    elif name == "HOME" or name == "PLAY":                            # the wheel's push (HOME); PLAY works too
        OPEN[0] = False
        pick = ITEMS[CHOICE[0]]
        if pick == "CANCEL":
            return "eat"
        ACTION[0] = "shutdown" if pick == "SHUT DOWN" else "stock"
        if ACTION[0] == "shutdown":
            try:
                open(SHUTDOWN_FLAG, "w").close()                       # mpc-console.sh switches the Sample off instead of starting the stock app
            except OSError:
                pass
        return "quit"
    elif isinstance(name, tuple) and name[0] == "KNOB" and name[1] == 11:
        try:
            import knobgate
            way = knobgate.gate(("exitmenu",), name[2], False, 1)
        except Exception:
            way = 1 if name[2] > 0 else -1
        if way:
            CHOICE[0] = (CHOICE[0] + (1 if way > 0 else -1)) % len(ITEMS)
    return "eat"


def draw(canvas, W, H):
    """Over whatever page is showing."""
    if not OPEN[0]:
        return
    c = canvas
    w, h = 240, 150
    x0, y0 = (W - w) // 2, (H - h) // 2
    c.rect(x0 - 2, y0 - 2, w + 4, h + 4, (255, 255, 255))
    c.rect(x0, y0, w, h, (14, 16, 14))
    c.text_px(x0 + 14, y0 + 26, "LEAVE CONSOLE", (232, 176, 75), 16, -1)
    for i, label in enumerate(ITEMS):
        y = y0 + 40 + i * 34
        on = i == CHOICE[0]
        if on:
            c.rect(x0 + 10, y, w - 20, 30, (255, 255, 255))
        c.text_px(x0 + 20, y + 22, label, (14, 16, 14) if on else (255, 255, 255), 16, -1)
