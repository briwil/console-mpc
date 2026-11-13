"""The page change card: when you go to another page (left button 1's INSTRUMENT > SEQUENCER > AUTOMATION,
left button 3's REVERB > DELAY > SONG INSERT 1 / 2, the instruments list, the tape...), a black screen with the
old page's name slides off to the left and the new one's slides in from the right, stays a moment, then the page
shows. 0.6 of a second in all; any button, knob or pad cuts it short. The Move's screen and the phone both."""
import time

HOLD_OLD = 0.05                 # the old page's name, before it slides
SLIDE = 0.2                     # the slide
HOLD_NEW = 0.35                 # the new page's name, after it
TOTAL = HOLD_OLD + SLIDE + HOLD_NEW


def label(T):
    """The page's name as the card shows it, or None (a list or menu over it: no card)."""
    fx = getattr(T, "fx_page", None)
    if fx:
        return {"reverb": "REVERB", "delay": "DELAY", "song1": "SONG INSERT 1", "song2": "SONG INSERT 2",
                "mixer": "MIXER"}.get(fx)
    if T.seq_page:
        ap = getattr(T, "auto_page", False)
        return "PUNCH FX" if ap == "punch" else "AUTOMATION" if ap else "SEQUENCER"
    if T.drum_page:
        return "INSTRUMENT"                              # (all of an instrument's pages: LFO, INSERT, SENDS, ARP, PADS too)
    if T.inst_page:
        return "INSTRUMENT SELECTION"
    if getattr(T, "song_page", False):
        return "SONG"
    return "TAPE"


class PageFX:
    def __init__(self):
        self.last = None
        self.anim = None            # {"id", "from", "to", "t0"}
        self._n = 0

    def update(self, T, menu=None):
        """Call before drawing: a new page starts the card."""
        if menu is not None and (menu.open or menu.kits.open):
            return                                       # (a menu over the page: no card, and none when it closes)
        if getattr(T, "sbrowse", None) is not None and T.sbrowse.active:
            return
        name = label(T)
        if name == self.last:
            return
        old, self.last = self.last, name
        if old is None or name is None:                  # (starting up)
            self.anim = None
            return
        self._n += 1
        self.anim = {"id": self._n, "from": old, "to": name, "t0": time.monotonic()}

    def cancel(self):
        self.anim = None

    def state(self):
        """(from, to, age) while the card shows, else None."""
        a = self.anim
        if a is None:
            return None
        age = time.monotonic() - a["t0"]
        if age >= TOTAL:
            self.anim = None
            return None
        return a["from"], a["to"], age

    def phone(self):
        s = self.state()
        return None if s is None else {"id": self.anim["id"], "from": s[0], "to": s[1], "age": round(s[2], 3)}


def offset(age, width):
    """How far left the old name has gone: 0 while it holds, width once the slide is over (eased)."""
    t = min(1.0, max(0.0, (age - HOLD_OLD) / SLIDE))
    t = t * t * (3 - 2 * t)
    return int(round(t * width))


def draw(f, card):
    """The card on the Move's screen (f: screen.Frame). card: (from, to, age)."""
    from screen import FONT, W, H
    old, new, age = card
    f.clear()
    dx = offset(age, W)
    _name(f, old, -dx, FONT, W, H)
    _name(f, new, W - dx, FONT, W, H)


def _name(f, s, x0, FONT, W, H):
    """A page name in double-size letters, centred on a 128-wide screen starting at x0 (two lines if long)."""
    lines = [s]
    if len(s) * 12 - 2 > W - 4 and " " in s:
        a, b = s.rsplit(" ", 1) if s.count(" ") == 1 or len(s.rsplit(" ", 1)[1]) > 2 else s.split(" ", 1)
        lines = [a, b]
    top = (H - (len(lines) * 14 + (len(lines) - 1) * 6)) // 2
    for k, line in enumerate(lines):
        gap = 12 if len(line) * 12 - 2 <= W - 4 else 11          # (11 letters: a little closer)
        w = len(line) * gap - 2
        x = x0 + (W - w) // 2
        y = top + k * 20
        for i, ch in enumerate(line):
            cols = FONT.get(ch, FONT["?"] if ch.strip() else FONT[" "])
            for col, bits in enumerate(cols):
                for row in range(7):
                    if bits >> row & 1:
                        f.rect(x + i * gap + col * 2, y + row * 2, 2, 2)
