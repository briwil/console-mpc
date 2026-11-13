"""Check the Move's button names: press any button and the screen shows what we think it is, with its number.
(Console mode must be running.)   python3 /data/UserData/console/move/buttons_test.py      Ctrl+C quits.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pi-app", "core"))
from core import Core  # noqa: E402

src = open(os.path.join(HERE, "move_test.py")).read()
ns = {"LAYOUT": "pages"}
exec(src[src.index("FONT = {"):src.index("# ---------------------------------------------------------------- shared state")], ns)
render_screen = ns["render"]

BUTTONS = {85: "PLAY", 86: "RECORD", 118: "SAMPLE", 58: "LOOP", 49: "SHIFT", 50: "MENU", 51: "BACK",
           52: "CAPTURE", 56: "UNDO", 60: "COPY", 119: "DELETE", 88: "MUTE", 55: "PLUS", 54: "MINUS",
           62: "LEFT", 63: "RIGHT", 3: "WHEEL PRESS", 43: "LEFT BUTTON 1", 42: "LEFT BUTTON 2",
           41: "LEFT BUTTON 3", 40: "LEFT BUTTON 4"}

c = Core()
c.display(render_screen(["BUTTON CHECK", "PRESS ANY BUTTON", "", ""]))
print("Press buttons; the Move's screen shows each one's name. Ctrl+C quits.")
try:
    while True:
        for _frame, m in c.read_midi():
            kind, num, val = m[0] & 0xF0, m[1], m[2]
            if kind == 0xB0 and num in BUTTONS and val:
                name = BUTTONS[num]
                c.display(render_screen(["BUTTON CHECK", name, "NUMBER %d" % num, ""]))
                print("%-14s (CC %d)" % (name, num))
            elif kind == 0xB0 and num == 14:
                c.display(render_screen(["BUTTON CHECK", "WHEEL " + ("RIGHT" if val < 64 else "LEFT"), "NUMBER 14", ""]))
        time.sleep(0.01)
except KeyboardInterrupt:
    pass
finally:
    c.display(render_screen([]))
    time.sleep(0.1)
    c.close()
