"""The screen's look (colours, fonts, sizes), from theme.json.

pi-app/theme.json holds the defaults (in the code, from GitHub). Changes made on the theme page
(http://console.local/theme) are saved to ~/console-data/theme.json and win over the defaults; the
app picks them up within half a second, so the screen changes while you edit.
"""
import copy
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = os.path.join(HERE, "theme.json")
DATA = os.path.realpath(os.path.expanduser(os.environ.get("CONSOLE_DATA", "~/console-data")))
USER = os.path.join(DATA, "theme.json")

_cache = {"checked": 0.0, "stamp": None, "theme": None, "version": 0}


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def merge(base, extra):
    """base with extra's values put in, only where base has that key (and the same kind of value)."""
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if k not in out:
            continue
        if isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
        elif isinstance(out[k], dict) or isinstance(v, dict):
            continue
        elif isinstance(out[k], str) and isinstance(v, str):
            out[k] = v
        elif isinstance(out[k], (int, float)) and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = type(out[k])(v) if isinstance(out[k], int) and float(v).is_integer() else v
    return out


def defaults():
    return _read(DEFAULTS)


def current():
    """The theme now: the defaults with the saved changes. Looks at the files at most twice a second."""
    now = time.monotonic()
    if _cache["theme"] is None or now - _cache["checked"] > 0.5:
        _cache["checked"] = now
        stamp = []
        for p in (DEFAULTS, USER):
            try:
                stamp.append(os.path.getmtime(p))
            except OSError:
                stamp.append(None)
        if stamp != _cache["stamp"]:
            _cache["stamp"] = stamp
            _cache["theme"] = merge(defaults(), _read(USER))
            _cache["version"] += 1
    return _cache["theme"]


def version():
    current()
    return _cache["version"]


def section(name):
    return current().get(name, {})


def rgb(hex_colour, fallback=(255, 0, 255)):
    h = str(hex_colour).lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def differences(base, full):
    """Only the values in full that differ from base, so new defaults still come through for the rest."""
    out = {}
    for k, v in full.items():
        if isinstance(v, dict):
            d = differences(base.get(k, {}), v)
            if d:
                out[k] = d
        elif base.get(k) != v:
            out[k] = v
    return out


def save(changes):
    """Keep the changes (only settings the defaults have, and only where they differ from them) in
    ~/console-data/theme.json. Returns the whole theme."""
    base = defaults()
    clean = merge(base, changes)
    os.makedirs(DATA, exist_ok=True)
    tmp = USER + ".part"
    with open(tmp, "w") as f:
        json.dump(differences(base, clean), f, indent=1)
    os.replace(tmp, USER)
    return clean


def reset():
    try:
        os.remove(USER)
    except OSError:
        pass
