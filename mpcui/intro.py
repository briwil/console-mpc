"""The start-up screen (made with the Sample Screen Designer): shown after Console starts, held until left button 1, 2 or 3
(B1 / B2 / B3 on the MPC) is pressed. native.publish draws it over the page."""
from native import BG, FG
import colour

GREEN0, GREEN1, GREEN2, GREEN3, GREEN4, GREEN5, GREEN6 = colour.GREENS[:7]


def draw_frame(c):
    c.clear(BG)
    c.rect(17, -62, 69, 74, GREEN5)
    c.rect(123, -62, 69, 74, GREEN3)
    c.rect(232, -62, 69, 74, GREEN2)
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
    c.text_px(145, 19, "MIXER", GREEN5, 8)
    c.text_px(140, 29, "REVERB", GREEN4, 8)
    c.rect(123, 21, 69, 1, GREEN5)
    c.rect(123, 31, 69, 1, GREEN4)
    c.text_px(144, 39, "DELAY", GREEN3, 8)
    c.rect(123, 41, 69, 1, GREEN3)
    c.text_px(123, 49, "SONG INSERT 1", GREEN2, 8)
    c.rect(123, 51, 69, 1, GREEN2)
    c.text_px(122, 59, "SONG INSERT 2", GREEN2, 8)
    c.rect(123, 61, 69, 1, GREEN1)
    c.text_px(255, 19, "TAPE", GREEN5, 8)
    c.rect(232, 21, 69, 1, GREEN5)
    c.text_px(67, 136, "WELCOME TO", FG, 16)
    c.text_px(81, 161, "CONSOLE", GREEN5, 32)
    import intro_bars                               # the two bent bars: exactly the start-up animation's last frame
    intro_bars.draw(c)
    import soundpage
    for n, x0 in ((1, 17), (2, 123), (3, 232)):                       # the names in the middle of their boxes
        t = "BTN %d" % n
        c.text_px(x0 + 34 - soundpage.c_w(c, 8, t) // 2, 8, t, BG, 8)


def frame_at(_t):
    """The one still frame (the argument is kept: native.py asks for the frame at a time)."""
    return draw_frame
