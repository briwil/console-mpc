"""No extended screen on the MPC: Console's big-screen web page (port 8080) is not started, and SETTINGS has no
EXTERNAL SCREEN row. (The page needs a phone or tablet on the same network; the MPC has no wifi.)"""
import random
import sys
import types

# what Console still asks of the module: the colour family of this start (the HELLO animation on the pads)
FAMILY = random.choice(["ORANGE", "GREEN", "YELLOW", "TEAL", "PURPLE"])
PAD_COLOUR = {"ORANGE": 3, "GREEN": 11, "YELLOW": 8, "TEAL": 15, "PURPLE": 22}


class _Settings(list):
    """MENU > SETTINGS: Console adds its SCREEN row while starting; here that row is refused."""

    def append(self, item):
        if item != "SCREEN":
            list.append(self, item)

    def insert(self, i, item):
        if item != "SCREEN":
            list.insert(self, i, item)


def install(menu_mod):
    stub = types.ModuleType("screenview")
    stub.FAMILY, stub.PAD_COLOUR = FAMILY, PAD_COLOUR
    stub.start = lambda *a, **k: None          # no web server
    stub.frame = lambda *a, **k: None          # no copy of the screen
    stub.address = lambda: ""
    sys.modules["screenview"] = stub
    menu_mod.SETTINGS = _Settings(r for r in menu_mod.SETTINGS if r != "SCREEN")
