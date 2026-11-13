"""Getting more instruments and effects from Schwung's catalog, straight onto the Move (no building).

Schwung's own catalog (module-catalog.json in charlesvestal/schwung on GitHub) lists every module and where its
ready-made download is: each module's GitHub release has a .tar.gz with the module's folder (module.json and the
compiled library, built for the Move). This reads the catalog, downloads one, and keeps it in schwung/modules/<id>/.
What's installed is listed in schwung-installed.json (next to the song data), and catalog.py adds those to the
instruments the app knows (sound generators) or the effects (audio_fx).

Nothing here can reach your files or settings: it downloads one file from github.com into a new folder.
"""
import json
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(HERE, "modules")
CATALOG_URL = "https://raw.githubusercontent.com/charlesvestal/schwung/main/module-catalog.json"
MAX_BYTES = 150 * 1024 * 1024


def data_dir():
    d = os.environ.get("CONSOLE_DATA")
    return os.path.dirname(d.rstrip("/")) if d else os.path.expanduser("~")


def registry_path():
    return os.path.join(data_dir(), "schwung-installed.json")


def installed():
    """{id: record} of what has been installed from the catalog."""
    try:
        return json.load(open(registry_path()))
    except (OSError, ValueError):
        return {}


def _get(url, limit=MAX_BYTES):
    req = urllib.request.Request(url, headers={"User-Agent": "console-move"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out, n = [], 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            n += len(chunk)
            if n > limit:
                raise RuntimeError("too big")
            out.append(chunk)
    return b"".join(out)


def fetch_catalog():
    """The catalog's modules (a list of dicts), or raises."""
    return json.loads(_get(CATALOG_URL, 20 * 1024 * 1024))["modules"]


def installable(mods, builtin_ids):
    """Sound generators and audio effects not already here, sorted by name."""
    have = set(builtin_ids) | set(installed())
    out = [m for m in mods if m.get("component_type") in ("sound_generator", "audio_fx")
           and m["id"] not in have and m.get("github_repo") and m.get("asset_name")]
    return sorted(out, key=lambda m: (m["component_type"] != "sound_generator", m["name"].lower()))


def _safe_extract(tar, dest):
    for m in tar.getmembers():
        target = os.path.realpath(os.path.join(dest, m.name))
        if not target.startswith(os.path.realpath(dest) + os.sep) and target != os.path.realpath(dest):
            raise RuntimeError("unsafe file in the download")
        if m.issym() or m.islnk() or m.isdev():
            raise RuntimeError("unexpected file type in the download")
    tar.extractall(dest)


def install(entry):
    """Download and install one catalog entry. Returns the record, or raises with what went wrong."""
    mid = entry["id"]
    if not mid.replace("-", "").replace("_", "").isalnum():
        raise RuntimeError("odd module name")
    url = "https://github.com/%s/releases/latest/download/%s" % (entry["github_repo"], entry["asset_name"])
    blob = _get(url)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.tar.gz")
        open(path, "wb").write(blob)
        out = os.path.join(tmp, "x")
        os.makedirs(out)
        with tarfile.open(path) as tar:
            _safe_extract(tar, out)
        folder = None
        for root, _dirs, files in os.walk(out):
            if "module.json" in files:
                folder = root
                break
        if folder is None:
            raise RuntimeError("no module.json in the download")
        info = json.load(open(os.path.join(folder, "module.json")))
        kind = "fx" if entry["component_type"] == "audio_fx" else (
            "drums" if entry.get("subcategory") == "drum-machine" else "synth")
        dsp = info.get("dsp") or ("%s.so" % mid if kind == "fx" else "dsp.so")
        so = os.path.join(folder, dsp)
        if not os.path.exists(so):
            cands = [f for f in os.listdir(folder) if f.endswith(".so")]
            if not cands:
                raise RuntimeError("no library in the download")
            so = os.path.join(folder, cands[0])
            dsp = cands[0]
        dest = os.path.join(MODULES_DIR, mid)
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(MODULES_DIR, exist_ok=True)
        shutil.copytree(folder, dest, symlinks=False)
        if kind != "fx" and dsp != "dsp.so":
            shutil.copy2(os.path.join(dest, dsp), os.path.join(dest, "dsp.so"))
    rec = {"id": mid, "title": entry["name"].upper(), "kind": kind, "description": entry.get("description", ""),
           "dsp": dsp, "repo": entry["github_repo"], "requires": entry.get("requires", "")}
    reg = installed()
    reg[mid] = rec
    tmpf = registry_path() + ".tmp"
    with open(tmpf, "w") as f:
        json.dump(reg, f)
    os.replace(tmpf, registry_path())
    return rec


def remove(mid):
    reg = installed()
    if mid in reg:
        del reg[mid]
        with open(registry_path(), "w") as f:
            json.dump(reg, f)
        shutil.rmtree(os.path.join(MODULES_DIR, mid), ignore_errors=True)


class Store:
    """The screen's side: loads the catalog in the background, installs one at a time."""

    def __init__(self, builtin_ids):
        self.builtin = list(builtin_ids)
        self.state = "idle"             # loading, ready, error, installing
        self.items = []
        self.msg = ""
        self._t = None

    def load(self):
        if self.state in ("loading", "installing"):
            return
        self.state, self.msg = "loading", "READING SCHWUNG'S LIST..."

        def run():
            try:
                self.items = installable(fetch_catalog(), self.builtin)
                self.state, self.msg = "ready", "%d AVAILABLE" % len(self.items)
            except Exception as e:                  # noqa: BLE001
                self.state, self.msg = "error", ("NO LIST: " + str(e))[:40].upper()
        threading.Thread(target=run, daemon=True, name="schwung list").start()

    def install(self, i):
        if self.state != "ready" or not 0 <= i < len(self.items):
            return
        entry = self.items[i]
        self.state, self.msg = "installing", "INSTALLING %s..." % entry["name"].upper()[:20]

        def run():
            try:
                rec = install(entry)
                import catalog
                catalog.add_record(rec["id"], rec)
                self.items = [m for m in self.items if m["id"] != entry["id"]]
                self.state, self.msg = "ready", "INSTALLED %s" % rec["title"][:22]
                self.just = rec
            except Exception as e:                  # noqa: BLE001
                self.state, self.msg = "ready", ("FAILED: " + str(e))[:40].upper()
        threading.Thread(target=run, daemon=True, name="schwung install").start()
