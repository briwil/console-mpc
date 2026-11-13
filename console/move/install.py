"""First install of Console on an Ableton Move. Run it on the Move (over SSH); the page's one-line command does that.

    python3 install.py

What it does, and nothing else:
  1. checks that this is a Move and that RNBO Move Takeover is installed (Console runs in its place),
  2. makes /data/UserData/console and the ENABLED file that tells the launcher to start Console,
  3. downloads move-update.py from GitHub, then lets it do the work: the app's files, the launcher
     (RNBO's own is kept as RNBOLauncher.orig), numpy and Pillow, the synths and drum machines, and the
     compiler (Zig) that builds the sound core and effects.

It is safe to run again: it only adds to or refreshes what is there. To go back to RNBO: delete
/data/UserData/console/ENABLED. Songs and settings live in /data/UserData/console and are left alone.
"""
import os
import subprocess
import sys
import urllib.request

BASE = os.environ.get("CONSOLE_BASE", "/data/UserData")
REPO = os.environ.get("CONSOLE_REPO", "briwil/console-move")
BRANCH = os.environ.get("CONSOLE_BRANCH", "main")
CONSOLE = os.path.join(BASE, "console")
RNBO_LAUNCHER = os.path.join(BASE, "rnbo", "bin", "RNBOLauncher")


def say(text=""):
    print(text, flush=True)


def stop(text):
    say()
    say("Stopped: " + text)
    sys.exit(1)


def main():
    say("Console installer")
    say("-----------------")
    if sys.version_info < (3, 6):
        stop("this needs Python 3.6 or newer (the Move has 3.10).")
    if not os.path.isdir(BASE):
        stop("%s isn't here. Run this on the Move itself (ssh ableton@move.local), not on your computer." % BASE)
    if not os.path.exists(RNBO_LAUNCHER):
        stop("RNBO Move Takeover isn't installed. Console starts through it: install it first (Cycling '74's "
             "installer for the Move), start it once from the Move's settings, then run this again.")
    say("1/3  RNBO Move Takeover is installed.")

    os.makedirs(os.path.join(CONSOLE, "move"), exist_ok=True)
    open(os.path.join(CONSOLE, "ENABLED"), "a").close()
    say("2/3  Console's folder is ready: %s" % CONSOLE)

    url = "https://raw.githubusercontent.com/%s/%s/move/move-update.py" % (REPO, BRANCH)
    say("3/3  Downloading the updater from GitHub...")
    try:
        data = urllib.request.urlopen(url, timeout=60).read()
    except Exception as e:                                   # noqa: BLE001
        stop("couldn't download %s (%s). Is the Move online (Wi-Fi), and is the project public?" % (url, e))
    updater = os.path.join(CONSOLE, "move", "move-update.py")
    with open(updater + ".new", "wb") as f:
        f.write(data)
    os.replace(updater + ".new", updater)

    say()
    say("Setting up the compiler (one time, about 45 MB)...")
    if subprocess.run([sys.executable, updater, "setup"]).returncode != 0:
        stop("the compiler download failed. Run this again when the Move is online.")
    say()
    say("Installing Console (this takes a few minutes the first time)...")
    if subprocess.run([sys.executable, updater]).returncode != 0:
        stop("the install didn't finish. Run this again; it carries on where it stopped.")
    say()
    say("Done. On the Move: Shift + Step 2 opens the Move's settings. Choose RNBO at the bottom of the list")
    say("and Console starts after a few seconds. To go back to RNBO, delete %s/ENABLED." % CONSOLE)


if __name__ == "__main__":
    main()
