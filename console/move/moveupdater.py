"""SOFTWARE UPDATE in the project menu's settings, on the Move: the same states as the Pi's updater.Updater
(menu.py drives it), but it asks GitHub's API instead of git, and installs with move-update.py (the app's files,
numpy/Pillow if missing, and the synths GitHub built). Then the app restarts (exit code 75: RNBOLauncher
starts it again)."""
import json
import os
import subprocess
import sys
import threading
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE = "/data/UserData/console"
TOKEN = os.path.join(CONSOLE, "github-token")
VERSION = os.path.join(CONSOLE, "version")          # "<commit sha> <date>", written by move-update.py
REPO = "briwil/console-move"
RESTART_CODE = 75


def _get(url):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "console-move-updater"}
    try:
        headers["Authorization"] = "Bearer " + open(TOKEN).read().strip()       # (not needed: the repo is public)
    except OSError:
        pass
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def label(sha):
    """What SOFTWARE UPDATE shows: the release number (move/VERSION), then the build's short code."""
    try:
        num = open(os.path.join(HERE, "VERSION")).read().strip()
    except OSError:
        num = ""
    return ("v%s  %s" % (num, sha[:7]) if num else sha[:7]).strip()


def installed():
    try:
        sha, _, date = open(VERSION).read().strip().partition(" ")
        return sha, date
    except OSError:
        return "", ""


class Updater:
    def __init__(self, log=print):
        self.log = log
        self.state = "idle"
        self.detail = ""
        self.count = 0
        self.needs_setup = False
        self.splash_changed = False
        self._new = None
        sha, date = installed()
        self.version = label(sha) if sha else "unknown"

    @property
    def busy(self):
        return self.state in ("checking", "installing")

    def check(self):
        if not self.busy:
            self.state, self.detail = "checking", ""
            threading.Thread(target=self._check, daemon=True, name="update check").start()

    def install(self):
        if self.state == "available":
            self.state = "installing"
            threading.Thread(target=self._install, daemon=True, name="update install").start()

    def _check(self):
        try:
            if not os.path.exists(TOKEN):
                raise RuntimeError("NO GITHUB KEY IN console/github-token")
            head = _get("https://api.github.com/repos/%s/commits/main" % REPO)
            new = head["sha"]
            old, _ = installed()
            if old and new.startswith(old):
                if self._new_libs():                     # the same code, but GitHub has built new libraries since
                    self._new = new
                    self.detail = "NEW SYNTH / EFFECT LIBRARIES"
                    self.count = 1
                    self.state = "available"
                    return
                self.state = "current"
                return
            self._new = new
            self.detail = head["commit"]["message"].splitlines()[0]
            self.count = 1
            if old:
                try:
                    self.count = _get("https://api.github.com/repos/%s/compare/%s...%s" % (REPO, old, new))[
                        "total_commits"] or 1
                except Exception:
                    pass
            self.state = "available"
        except Exception as e:
            self.state, self.detail = "error", str(e).upper()[:60]
            self.log("Update check failed: %s" % e)

    @staticmethod
    def _new_libs():
        """True if GitHub's built libraries (release libs-latest) aren't the ones installed (console/libs-version,
        written by move-update.py). They're built a while after the code is pushed, so an update installed in
        between gets the code but the old libraries: this lets the next update get them."""
        try:
            rel = _get("https://api.github.com/repos/%s/releases/tags/libs-latest" % REPO)
            asset = [a for a in rel.get("assets", []) if a["name"] == "move-libs.tgz"][0]
            want = "%s %s" % (asset["id"], asset["updated_at"])
            have = open(os.path.join(CONSOLE, "libs-version")).read()
            return want != have
        except Exception:                                    # noqa: BLE001
            return False

    def _install(self):
        script = os.path.join(HERE, "move-update.py")
        r = subprocess.run([sys.executable, script], capture_output=True, text=True)
        self.log(r.stdout[-3000:] + r.stderr[-2000:])
        if r.returncode != 0:
            last = (r.stderr or r.stdout).strip().splitlines()
            self.state, self.detail = "error", (last[-1] if last else "FAILED").upper()[:60]
            return
        sha, date = installed()
        self.version = label(sha)
        self.state = "done"
