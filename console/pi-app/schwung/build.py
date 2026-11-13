"""Fetch and build the Schwung sound generators listed in catalog.py, on the Pi itself.

Each module is fetched from GitHub at the exact version catalog.py names (so an update upstream can't
change what Console runs without us looking at it first) and compiled with the Pi's own gcc / g++,
the way its own build script does it for the Move. The results go in schwung/modules/<id>/ (not kept in
git): dsp.so and module.json, the two files a module is.

  python3 schwung/build.py            build every module that's missing or out of date
  python3 schwung/build.py forge      just that one (or several)
  python3 schwung/build.py --list     what's there

The app runs it in the background at start-up (at low priority) for anything missing, so a software
update that adds a module needs nothing else; run it by hand to watch it work.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import catalog  # noqa: E402

SRC = os.path.join(HERE, "src")          # the modules' code, one folder each
OUT = os.path.join(HERE, "modules")      # the built modules
HOST_LIB = os.path.join(HERE, "libschwunghost.so")
DATA = os.environ.get("CONSOLE_DATA", os.path.expanduser("~/console-data"))
LOCAL_CMAKE = os.path.expanduser("~/.local/bin/cmake")


def log(msg):
    print("Schwung modules: %s" % msg, flush=True)


def run(cmd, cwd, timeout=1800):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-600:] or "failed")
    return r.stdout


def cmake():
    """cmake: the system's, or one installed for this user with pip (no password needed)."""
    found = shutil.which("cmake") or (LOCAL_CMAKE if os.path.exists(LOCAL_CMAKE) else None)
    if found:
        return found
    log("installing cmake (for this user)...")
    run([sys.executable, "-m", "pip", "install", "--user", "--break-system-packages", "--quiet", "cmake"], HERE)
    return LOCAL_CMAKE


def build_host():
    """libschwunghost.so: the small host that loads modules (host.c)."""
    src = os.path.join(HERE, "host.c")
    if os.path.exists(HOST_LIB) and os.path.getmtime(HOST_LIB) >= max(
            os.path.getmtime(src), os.path.getmtime(os.path.join(HERE, "plugin_api_v1.h"))):
        return True
    try:
        run(["gcc", "-O2", "-shared", "-fPIC", "-o", HOST_LIB + ".tmp", src, "-ldl", "-lpthread"], HERE)
        os.replace(HOST_LIB + ".tmp", HOST_LIB)
        return True
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        log("couldn't build the host: %s" % e)
        return False


def fetch(m):
    """The module's code at its pinned commit, in src/<id>/."""
    d = os.path.join(SRC, m["id"])
    stamp = os.path.join(d, ".console-commit")
    if os.path.exists(stamp) and open(stamp).read().strip() == m["commit"]:
        return d
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    url = "https://github.com/%s.git" % m["repo"]
    run(["git", "init", "-q"], d)
    run(["git", "fetch", "-q", "--depth", "1", url, m["commit"]], d, timeout=900)
    run(["git", "checkout", "-q", "FETCH_HEAD"], d)
    for sub in m.get("submodules", []):
        run(["git", "submodule", "update", "--init", "--depth", "1", sub], d, timeout=900)
    with open(stamp, "w") as f:
        f.write(m["commit"])
    return d


def built(m):
    if m.get("asset"):
        return os.path.exists(os.path.join(OUT, m["id"], "module.json")) and (
            m.get("kind") == "fx" or os.path.exists(os.path.join(OUT, m["id"], "dsp.so")))
    if m.get("prebuilt"):
        return True                      # installed ready-made from Schwung's catalog (store.py)
    stamp = os.path.join(OUT, m["id"], ".console-commit")
    return os.path.exists(os.path.join(OUT, m["id"], "dsp.so")) and os.path.exists(stamp) \
        and open(stamp).read().strip() == m["commit"] + catalog.recipe_version(m)


def tarfile_error():
    import tarfile
    return tarfile.TarError


def fetch_asset(m):
    """A module Schwung publishes ready-made for the Move: download its release file into modules/<id>/."""
    import tarfile
    import tempfile
    import urllib.request
    url = "https://github.com/%s/releases/latest/download/%s" % (m["repo"], m["asset"])
    req = urllib.request.Request(url, headers={"User-Agent": "console-move"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read(200 * 1024 * 1024)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.tar.gz")
        open(path, "wb").write(blob)
        out = os.path.join(tmp, "x")
        os.makedirs(out)
        with tarfile.open(path) as tar:
            for t in tar.getmembers():
                target = os.path.realpath(os.path.join(out, t.name))
                if not target.startswith(os.path.realpath(out)) or t.issym() or t.islnk() or t.isdev():
                    raise RuntimeError("unexpected file in the download")
            tar.extractall(out, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(out)
        folder = None
        for root, _dirs, files in os.walk(out):
            if "module.json" in files:
                folder = root
                break
        if folder is None:
            raise RuntimeError("no module.json in the download")
        info = json.load(open(os.path.join(folder, "module.json")))
        dsp = info.get("dsp") or "dsp.so"
        if not os.path.exists(os.path.join(folder, dsp)):
            cands = [f for f in os.listdir(folder) if f.endswith(".so")]
            if not cands:
                raise RuntimeError("no library in the download")
            dsp = cands[0]
        dest = os.path.join(OUT, m["id"])
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(folder, dest, symlinks=False)
        if dsp != "dsp.so" and m.get("kind") != "fx":
            shutil.copy2(os.path.join(dest, dsp), os.path.join(dest, "dsp.so"))


EXTRAS = os.path.join(HERE, "extras")    # our own additions to a module's folder (more preset banks), kept in git


def add_extras(mid, out_dir):
    """extras/<id>/ copied into the built module's folder (OB-Xd's presets/, Dexed's banks/...)."""
    src = os.path.join(EXTRAS, mid)
    if not os.path.isdir(src):
        return
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dst = os.path.normpath(os.path.join(out_dir, rel))
        os.makedirs(dst, exist_ok=True)
        for f in files:
            if not f.endswith(".py"):
                shutil.copy2(os.path.join(root, f), os.path.join(dst, f))


def build(m):
    """Fetch and compile one module. Returns None if it worked, else what went wrong."""
    if built(m):
        add_extras(m["id"], os.path.join(OUT, m["id"]))     # (added to since it was built: copied in now)
        return None
    if m.get("asset"):
        try:
            log("downloading %s..." % m["title"])
            fetch_asset(m)
            log("%s ready" % m["title"])
            return None
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, tarfile_error()) as e:
            log("couldn't get %s: %s" % (m["title"], e))
            return str(e)
    try:
        log("fetching %s..." % m["title"])
        d = fetch(m)
        for rel, old, new in m.get("patches", []):        # Console's own fixes to the module's code (catalog.py)
            path = os.path.join(d, rel)
            text = open(path).read()
            if new not in text:
                if old not in text:
                    raise RuntimeError("its code changed: a fix in catalog.py doesn't fit %s" % rel)
                open(path, "w").write(text.replace(old, new, 1))
        out_dir = os.path.join(OUT, m["id"])
        os.makedirs(out_dir, exist_ok=True)
        tmp = os.path.join(out_dir, "dsp.so.tmp")
        log("building %s..." % m["title"])
        for step in m["build"]:
            args = []
            for a in step:
                if "*" in a:                        # a wildcard: the files it matches, in order
                    found = sorted(glob.glob(os.path.join(d, a)))
                    args += [os.path.relpath(f, d) for f in found] or [a]
                elif a == "{cmake}":
                    args.append(cmake())
                else:
                    args.append(a.replace("{out}", tmp))
            run(args, d, timeout=3 * 3600)
        os.replace(tmp, os.path.join(out_dir, "dsp.so"))
        # module.json, and anything else the module reads from its folder (presets, kits...)
        shutil.copyfile(os.path.join(d, m["json"]), os.path.join(out_dir, "module.json"))
        for rel in m.get("files", []):
            src = os.path.join(d, rel)
            dst = os.path.join(out_dir, os.path.basename(rel.rstrip("/")))
            if os.path.isdir(src):
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
            elif os.path.exists(src):
                shutil.copy2(src, dst)              # keeps a helper program runnable
        add_extras(m["id"], out_dir)
        if m.get("roms"):
            # the module looks for ROMs in its own roms/ folder: that's ~/console-data/roms/<name>, which
            # the file page (http://console.local) can upload to
            roms = os.path.join(DATA, "roms", m["roms"])
            os.makedirs(roms, exist_ok=True)
            link = os.path.join(out_dir, "roms")
            if os.path.islink(link) or os.path.isfile(link):
                os.remove(link)
            elif os.path.isdir(link):
                shutil.rmtree(link)
            os.symlink(roms, link)
        with open(os.path.join(out_dir, ".console-commit"), "w") as f:
            f.write(m["commit"] + catalog.recipe_version(m))
        log("%s ready" % m["title"])
        return None
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        log("couldn't build %s: %s" % (m["title"], e))
        return str(e)


def main(args):
    if "--list" in args:
        for m in catalog.MODULES + catalog.FX_ASSETS:
            print("%-14s %-6s %s" % (m["id"], m["kind"], "built" if built(m) else "-"))
        return 0
    if not build_host():
        return 1
    want = [m for m in catalog.MODULES + catalog.FX_ASSETS if not args or m["id"] in args]
    bad = [m["title"] for m in want if build(m)]
    if bad:
        log("not built: %s" % ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
