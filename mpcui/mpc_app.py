"""Starts Console on the MPC Sample with its native 320 x 240 screens (mpcui/native.py) laid over Console's own pages.
Console's files are not changed: this adds the same search paths app.py does, wraps pages.draw, then runs app.py."""
import os
import runpy
import sys

C = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
APP_PY = os.path.join(C, "move", "app.py")
sys.path[:0] = [os.path.join(C, "tools", "sim", "stubs"), os.path.join(C, "pi-app"), os.path.join(C, "move"),
                os.path.dirname(os.path.abspath(__file__))]
os.environ.setdefault("CONSOLE_PLATFORM", "move")
try:
    import pygame
    pygame.init()
    import pages
    import native
    native.install(pages)
except Exception:
    import traceback
    print("native screens are off:\n" + traceback.format_exc(), flush=True)
sys.argv[0] = APP_PY
runpy.run_path(APP_PY, run_name="__main__")
