"""Update Console on the Move, on the Move itself: no Pi, no Mac.

    python3 /data/UserData/console/move/move-update.py              get the latest from GitHub and build
    python3 /data/UserData/console/move/move-update.py setup        one time: install the compiler (Zig)

It downloads briwil/console-move from GitHub (a private repo: it needs a read-only access key, saved in
/data/UserData/console/github-token), puts the app's files in /data/UserData/console, and builds the C parts
that change most (the sound core and the effects) with Zig, a compiler that is a single download and builds
for exactly the Move's system (glibc 2.35). The drum machines and synths are built by GitHub itself
(.github/workflows/move-libs.yml publishes them as the "libs-latest" release); this downloads them, and
installs numpy and Pillow (pip --user) if they are missing. No Pi, no Mac.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

BASE = "/data/UserData"
CONSOLE = os.path.join(BASE, "console")
TOKEN = os.path.join(CONSOLE, "github-token")
ZIG_VERSION = "0.13.0"
ZIG_DIR = os.path.join(BASE, "zig")
ZIG = os.path.join(ZIG_DIR, "zig")
REPO = "briwil/console-move"
SKIP = ("pi-app/splash/", "pi-app/schwung/src/", "pi-app/schwung/modules/")
TARGET = "aarch64-linux-gnu.2.35"


def say(text):
    print(text, flush=True)


def setup():
    """Download Zig into /data/UserData/zig (about 45 MB)."""
    if os.path.exists(ZIG):
        say("Zig is already installed: %s" % ZIG)
        return
    url = "https://ziglang.org/download/%s/zig-linux-aarch64-%s.tar.xz" % (ZIG_VERSION, ZIG_VERSION)
    say("Downloading Zig %s (about 45 MB)..." % ZIG_VERSION)
    tmp = os.path.join(BASE, "Scratch", "zig.tar.xz")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    urllib.request.urlretrieve(url, tmp)
    say("Unpacking...")
    out = os.path.join(BASE, "Scratch", "zig-unpack")
    shutil.rmtree(out, ignore_errors=True)
    try:
        with tarfile.open(tmp, "r:xz") as t:
            t.extractall(out)
    except (tarfile.CompressionError, ImportError):
        os.makedirs(out, exist_ok=True)                  # this Python can't read .xz: the system's tar can
        subprocess.run(["tar", "xJf", tmp, "-C", out], check=True)
    inner = os.path.join(out, os.listdir(out)[0])
    shutil.rmtree(ZIG_DIR, ignore_errors=True)
    shutil.move(inner, ZIG_DIR)
    os.remove(tmp)
    say("Installed: %s" % subprocess.run([ZIG, "version"], capture_output=True, text=True).stdout.strip())


def download():
    """The latest main branch, as a tar archive in memory."""
    req = _api("https://api.github.com/repos/%s/tarball/main" % REPO)
    say("Downloading the latest from GitHub...")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _api(url, accept="application/vnd.github+json"):
    """A GitHub request. With an access key saved (a private project) it is sent with it; without one the project
    must be public."""
    headers = {"Accept": accept, "User-Agent": "console-move-updater"}
    if os.path.exists(TOKEN):
        headers["Authorization"] = "Bearer " + open(TOKEN).read().strip()
    return urllib.request.Request(url, headers=headers)


def fetch_libs():
    """The drum machines, synths and the rest of the .so files, built by GitHub (release "libs-latest").
    Skipped when this one is already installed."""
    stamp = os.path.join(CONSOLE, "libs-version")
    try:
        with urllib.request.urlopen(_api("https://api.github.com/repos/%s/releases/tags/libs-latest" % REPO),
                                    timeout=60) as r:
            rel = json.load(r)
        asset = [a for a in rel.get("assets", []) if a["name"] == "move-libs.tgz"][0]
    except Exception as e:
        say("No built libraries on GitHub yet (%s). Run the 'Build Move libraries' action on GitHub." % e)
        return False
    version = "%s %s" % (asset["id"], asset["updated_at"])
    if os.path.exists(stamp) and open(stamp).read() == version:
        say("Libraries are up to date.")
        return True
    say("Downloading the synths and drum machines (%d MB)..." % (asset["size"] // 1048576))
    try:
        # GitHub answers with a redirect to its file storage, which must not get the access key
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            data = opener.open(_api(asset["url"], "application/octet-stream"), timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise
            data = urllib.request.urlopen(e.headers["Location"], timeout=600).read()
    except Exception as e:
        say("Couldn't download the libraries: %s" % e)
        return False
    app = os.path.join(CONSOLE, "pi-app")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        members = [m for m in t.getmembers() if ".." not in m.name.split("/") and not os.path.isabs(m.name)]
        for m in members:
            # each file written beside the old one, then swapped in: writing over a library Console has loaded
            # changed its code under it, and Console crashed in the middle of the update
            dest = os.path.join(app, m.name)
            if m.isdir():
                os.makedirs(dest, exist_ok=True)
            elif m.isfile():
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with t.extractfile(m) as src, open(dest + ".new", "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(dest + ".new", m.mode & 0o777 or 0o644)
                os.utime(dest + ".new", (m.mtime, m.mtime))
                os.replace(dest + ".new", dest)
    with open(stamp, "w") as f:
        f.write(version)
    say("Installed %d library files." % len(members))
    return True


def ensure_python_parts():
    """numpy and Pillow, with pip --user (as the ableton user), if the app can't find them."""
    def have():
        return subprocess.run([sys.executable, "-c", "import numpy, PIL"], capture_output=True).returncode == 0
    if have():
        return
    say("Installing numpy and Pillow (a few minutes)...")
    if subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True).returncode != 0:
        if subprocess.run([sys.executable, "-m", "ensurepip", "--user"], capture_output=True).returncode != 0:
            tmp = os.path.join(BASE, "Scratch", "get-pip.py")
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", tmp)
            subprocess.run([sys.executable, tmp, "--user"], check=False)
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "numpy", "Pillow"])
    say("numpy and Pillow are installed." if r.returncode == 0 and have() else
        "Couldn't install numpy / Pillow: tell Claude what is printed above.")


def unpack(data):
    """Puts pi-app/, move/ and the simulator's stand-ins (tools/sim/stubs/, the Move app uses them) from the archive into /data/UserData/console, over what's there (files that
    aren't in the archive, like the built libraries, stay)."""
    n, top = 0, ""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        for m in t.getmembers():
            parts = m.name.split("/", 1)                 # the archive's top folder is "<owner>-<repo>-<commit>"
            top = top or parts[0]
            if len(parts) < 2:
                continue
            rel = parts[1]
            if not (rel.startswith(("pi-app/", "move/", "tools/sim/stubs/"))) or (rel + "/").startswith(SKIP):
                continue
            if ".." in rel.split("/") or os.path.isabs(rel):
                continue                                 # never write outside the console folder
            dest = os.path.join(CONSOLE, rel)
            if m.isdir():
                os.makedirs(dest, exist_ok=True)
            elif m.isfile():
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with t.extractfile(m) as src, open(dest + ".new", "wb") as out:
                    shutil.copyfileobj(src, out)
                os.replace(dest + ".new", dest)
                if m.mode & 0o111:
                    os.chmod(dest, 0o755)
                n += 1
    say("Updated %d files." % n)
    if top:                                              # the version (the menu's SOFTWARE UPDATE compares it)
        with open(os.path.join(CONSOLE, "version"), "w") as f:
            f.write("%s %s" % (top.rsplit("-", 1)[-1], time.strftime("%b %d %Y")))


LAUNCHER = os.path.join(BASE, "rnbo", "bin", "RNBOLauncher")


def install_launcher():
    """Console mode's launcher (move/RNBOLauncher) in RNBO's place, if it was put there once by hand (the
    original kept as RNBOLauncher.orig) and has changed. Swapped in as a new file, so a running one is safe."""
    mine = os.path.join(CONSOLE, "move", "RNBOLauncher")
    if not os.path.exists(mine) or not os.path.exists(LAUNCHER):
        return
    if not os.path.exists(LAUNCHER + ".orig"):
        if not os.path.exists(os.path.join(CONSOLE, "ENABLED")):
            return                                   # console mode isn't wanted (yet): leave RNBO alone
        shutil.copy2(LAUNCHER, LAUNCHER + ".orig")   # first time (or after a factory reset): keep RNBO's
        say("Kept RNBO's own launcher as RNBOLauncher.orig.")
    new = open(mine, "rb").read()
    if os.path.exists(LAUNCHER) and open(LAUNCHER, "rb").read() == new:
        return
    with open(LAUNCHER + ".new", "wb") as out:
        out.write(new)
    os.chmod(LAUNCHER + ".new", 0o755)
    os.replace(LAUNCHER + ".new", LAUNCHER)
    say("Updated the console-mode launcher.")


def mark_built(app):
    """The libraries must look newer than their code, or the app tries to rebuild them (with a compiler it
    doesn't have)."""
    now = time.time()
    for root, _dirs, files in os.walk(app):
        for f in files:
            if f.endswith(".so"):
                os.utime(os.path.join(root, f), (now, now))


def build():
    app = os.path.join(CONSOLE, "pi-app")
    if not os.path.exists(ZIG):
        say("No compiler (fine: the libraries come from GitHub). The core and effects weren't rebuilt here.")
        mark_built(app)
        return True
    jobs = [("the sound core", ["core/core.c"], "core/libconsolecore.so", ["-ldl", "-lm"]),
            ("the effects", ["fx/fx.c"], "fx/libconsolefx.so", ["-lm"])]
    ok = True
    for label, srcs, out, libs in jobs:
        say("Building %s..." % label)
        cmd = [ZIG, "cc", "-target", TARGET, "-O2", "-shared", "-fPIC",
               "-o", os.path.join(app, out + ".new")] + [os.path.join(app, s) for s in srcs] + libs
        r = subprocess.run(cmd, capture_output=True, text=True,
                           env=dict(os.environ, ZIG_GLOBAL_CACHE_DIR=os.path.join(BASE, "Scratch", "zig-cache")))
        if r.returncode != 0:
            say("  couldn't build %s:\n%s" % (label, (r.stderr or r.stdout)[-1500:]))
            ok = False
            continue
        os.replace(os.path.join(app, out + ".new"), os.path.join(app, out))
    mark_built(app)
    return ok


if __name__ == "__main__":
    if sys.argv[1:] == ["setup"]:
        setup()
    else:
        unpack(download())
        install_launcher()
        ensure_python_parts()
        fetch_libs()
        say("Done." if build() else "Done (see above).")
