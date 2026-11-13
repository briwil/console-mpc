"""Software update: checks GitHub for a newer version of Console, installs it, and asks for a restart.

It's a git pull of the folder the app runs from, done in the background so the screen keeps going.
Uses the GitHub login the Pi already has for git pull (the repository is private): if git asks for
a password, this can't type it, so it says so instead of waiting.
"""
import os
import subprocess
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RESTART_CODE = 75                 # run.sh starts the app again when it exits with this
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="/bin/true", SSH_ASKPASS="/bin/true",
           GIT_SSH_COMMAND="ssh -o BatchMode=yes")


def git(*args, timeout=90):
    try:
        r = subprocess.run(["git", "-C", REPO] + list(args), capture_output=True, text=True,
                           timeout=timeout, env=ENV)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timed out"
    except OSError as e:
        return 1, "", str(e)


def explain(err):
    """git's error, in a few words for the screen."""
    e = err.lower()
    if "could not resolve host" in e or "unable to access" in e or "network is unreachable" in e or "timed out" in e:
        return "NO INTERNET CONNECTION"
    if "authentication" in e or "terminal prompts disabled" in e or "could not read username" in e \
            or "permission denied" in e:
        return "GITHUB LOGIN NEEDED (SEE CONTROLS.MD)"
    if "would be overwritten" in e or "not possible to fast-forward" in e or "diverging" in e:
        return "FILES ON THE PI WERE CHANGED BY HAND (SEE CONTROLS.MD)"
    if "not a git repository" in e:
        return "THIS COPY ISN'T FROM GITHUB"
    first = err.splitlines()[0] if err else "SOMETHING WENT WRONG"
    return first[:60].upper()


class Updater:
    def __init__(self, log=print):
        self.log = log
        self.state = "idle"        # idle, checking, current, available, installing, done, error
        self.detail = ""           # what the newest change is, or what went wrong
        self.count = 0             # how many changes are waiting
        self.needs_setup = False   # the update changed setup.sh: run it once
        self.splash_changed = False
        code, out, _ = git("log", "-1", "--format=%h  %cd", "--date=format:%b %d %Y", timeout=10)
        self.version = out if code == 0 and out else "unknown"

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
        code, _, err = git("fetch", "--quiet")
        if code != 0:
            self.state, self.detail = "error", explain(err)
            self.log("Update check failed: %s" % err)
            return
        code, out, err = git("rev-list", "--count", "HEAD..@{u}", timeout=10)
        if code != 0:
            self.state, self.detail = "error", explain(err)
            return
        self.count = int(out or 0)
        if self.count == 0:
            self.state, self.detail = "current", ""
            return
        _, subject, _ = git("log", "-1", "--format=%s", "@{u}", timeout=10)
        self.state, self.detail = "available", subject

    def _install(self):
        _, old, _ = git("rev-parse", "HEAD", timeout=10)
        code, _, err = git("pull", "--ff-only", "--quiet", timeout=300)
        if code != 0:
            self.state, self.detail = "error", explain(err)
            self.log("Update failed: %s" % err)
            return
        _, changed, _ = git("diff", "--name-only", old, "HEAD", timeout=10)
        files = changed.splitlines()
        self.needs_setup = "pi-app/setup.sh" in files
        self.splash_changed = any(f.startswith("pi-app/splash/") for f in files)
        if any(f.startswith("pi-app/web/") or f in ("pi-app/theme.py", "pi-app/theme.json") for f in files):
            try:                                    # the file page runs on its own: restart it on the new code
                subprocess.run(["sudo", "-n", "systemctl", "try-restart", "console-web"], capture_output=True,
                               timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass
        _, self.version, _ = git("log", "-1", "--format=%h  %cd", "--date=format:%b %d %Y", timeout=10)
        self.log("Updated to %s (%d changes)" % (self.version, self.count))
        self.state = "done"
