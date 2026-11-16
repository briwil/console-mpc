"""The start-up screen (made with the Sample Screen Designer): shown after Console starts, held until left button 1, 2 or 3
(B1 / B2 / B3 on the MPC) is pressed. native.publish draws it over the page."""
from native import BG, FG
import colour

_BARS = {}
GREEN0, GREEN1, GREEN2, GREEN3, GREEN4, GREEN5, GREEN6 = colour.GREENS[:7]


def draw_frame(c):
    c.clear(BG)
    c.rect(17, -62, 69, 74, GREEN5)
    c.rect(121, -62, 69, 74, GREEN3)
    c.rect(228, -62, 69, 74, GREEN2)
    c.text_px(23, 19, "INSTRUMENT", GREEN5, 8)
    c.text_px(22, 26, "PARAMETERS", GREEN5, 8)
    c.text_px(25, 36, "SEQUENCER", GREEN4, 8)
    c.rect(17, 28, 69, 1, GREEN5)
    c.rect(17, 38, 69, 1, GREEN4)
    c.text_px(22, 46, "AUTOMATION", GREEN3, 8)
    c.rect(17, 48, 69, 1, GREEN3)
    c.text_px(27, 56, "PUNCH FX", GREEN2, 8)
    c.rect(17, 58, 69, 1, GREEN2)
    c.text_px(37, 66, "SONG", GREEN2, 8)
    c.rect(17, 68, 69, 1, GREEN1)
    c.text_px(143, 19, "MIXER", GREEN5, 8)
    c.text_px(138, 29, "REVERB", GREEN4, 8)
    c.rect(121, 21, 69, 1, GREEN5)
    c.rect(121, 31, 69, 1, GREEN4)
    c.text_px(142, 39, "DELAY", GREEN3, 8)
    c.rect(121, 41, 69, 1, GREEN3)
    c.text_px(121, 49, "SONG INSERT 1", GREEN2, 8)
    c.rect(121, 51, 69, 1, GREEN2)
    c.text_px(120, 59, "SONG INSERT 2", GREEN2, 8)
    c.rect(121, 61, 69, 1, GREEN1)
    c.text_px(251, 19, "TAPE", GREEN5, 8)
    c.rect(228, 21, 69, 1, GREEN5)
    c.text_px(71, 140, "WELCOME TO", FG, 16)
    c.text_px(85, 165, "CONSOLE", GREEN5, 32)
    # the two bent bars: the instruments page's (soundpage.bands: same colours, thickness and curve), at this page's place
    for key, y, vx, r, col in (("outer", 91.5, 302.5, 59.5, colour.GREENS[3]), ("inner", 104.5, 289.5, 46.4, colour.GREENS[2])):
        m = _BARS.get(key)
        if m is None:
            import numpy as np
            import soundpage
            m = np.zeros((soundpage.H, soundpage.W), bool)
            soundpage._band_stroke(m, y, vx - r, r, 10.5)
            _BARS[key] = m
        c.px[m] = col
    c.text_px(38, 8, "BTN 1", BG, 8)
    c.text_px(142, 8, "BTN 2", BG, 8)
    c.text_px(244, 8, "BTN 3", BG, 8)


def frame_at(_t):
    """The one still frame (the argument is kept: native.py asks for the frame at a time)."""
    return draw_frame
