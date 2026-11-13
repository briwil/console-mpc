"""Wi-Fi from the SETTINGS page: which network the Pi is on, the networks nearby, connecting and
forgetting. Uses NetworkManager's nmcli (Pi OS's own network manager), so networks added here are the
same ones the Pi knows anyway. Console runs as a service, so nmcli goes through sudo (the Pi's first
user can use sudo without a password); if that isn't allowed it tries nmcli on its own.

Scanning and connecting take seconds, so they run in the background: the menu shows `busy` and
`message` while they do.
"""
import subprocess
import threading
import time

_prefix = None
_status = (0.0, None)


def _cmd():
    global _prefix
    if _prefix is None:
        try:
            ok = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        _prefix = ["sudo", "-n", "nmcli"] if ok else ["nmcli"]
    return list(_prefix)


def nmcli(*args, timeout=30):
    """(ok, stdout, stderr)"""
    try:
        r = subprocess.run(_cmd() + list(args), capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout, r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "timed out"
    except OSError as e:
        return False, "", str(e)


def split(line):
    """nmcli -t fields are separated by ':', with ':' inside a field written as '\\:'."""
    out, cur, i = [], "", 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if line[i] == ":":
            out.append(cur)
            cur = ""
        else:
            cur += line[i]
        i += 1
    out.append(cur)
    return out


_checking = threading.Lock()


def current():
    """The network the Pi is on (None: not connected). Never waits: it's looked up in the background
    every few seconds, and this returns the last answer."""
    global _status
    if time.monotonic() - _status[0] > 3.0 and _checking.acquire(blocking=False):
        threading.Thread(target=_check, daemon=True, name="wifi status").start()
    return _status[1]


def _check():
    global _status
    try:
        _status = (time.monotonic(), _lookup())
    finally:
        _checking.release()


def _lookup():
    ok, out, _ = nmcli("-t", "-f", "ACTIVE,SSID", "dev", "wifi", timeout=10)
    ssid = None
    if ok:
        for line in out.splitlines():
            f = split(line)
            if len(f) >= 2 and f[0] == "yes" and f[1]:
                ssid = f[1]
                break
    return ssid


def saved():
    """Names of the Wi-Fi networks the Pi has saved."""
    ok, out, _ = nmcli("-t", "-f", "NAME,TYPE", "con", "show", timeout=10)
    names = set()
    if ok:
        for line in out.splitlines():
            f = split(line)
            if len(f) >= 2 and f[1] in ("802-11-wireless", "wifi"):
                names.add(f[0])
    return names


def explain(err):
    e = err.lower()
    if "secrets were required" in e or "802-1x" in e or "password" in e or "psk" in e:
        return "WRONG PASSWORD?"
    if "no network with ssid" in e or "not found" in e:
        return "NETWORK NOT FOUND (OUT OF RANGE?)"
    if "not authorized" in e or "permission" in e or "sudo" in e:
        return "NOT ALLOWED TO CHANGE THE NETWORK"
    if "timed out" in e:
        return "TIMED OUT"
    first = err.splitlines()[0] if err else "SOMETHING WENT WRONG"
    return first.replace("Error: ", "")[:60].upper()


class Wifi:
    def __init__(self):
        self.networks = []          # [{"ssid", "signal", "secure", "active", "saved"}], strongest first
        self.busy = ""              # "SCANNING" or "CONNECTING", while it's working
        self.message = ""           # how the last scan or connection went

    def scan(self):
        if self.busy:
            return
        self.busy, self.message = "SCANNING", ""
        threading.Thread(target=self._scan, daemon=True, name="wifi scan").start()

    def _scan(self):
        ok, out, err = nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes",
                             timeout=30)
        if not ok:
            self.busy, self.message = "", "COULDN'T SCAN: " + explain(err)
            return
        known = saved()
        best = {}
        for line in out.splitlines():
            f = split(line)
            if len(f) < 4 or not f[1]:
                continue                        # hidden networks have no name: skip them
            n = {"ssid": f[1], "signal": int(f[2] or 0), "secure": f[3] not in ("", "--"),
                 "active": f[0].strip() == "*", "saved": f[1] in known}
            old = best.get(n["ssid"])
            if old is None or n["signal"] > old["signal"] or n["active"]:
                n["active"] = n["active"] or bool(old and old["active"])
                best[n["ssid"]] = n
        self.networks = sorted(best.values(), key=lambda n: (not n["active"], -n["signal"]))
        self.busy = ""
        if not self.networks:
            self.message = "NO NETWORKS FOUND"

    def connect(self, ssid, password=None):
        if self.busy:
            return
        self.busy, self.message = "CONNECTING", ""
        threading.Thread(target=self._connect, args=(ssid, password), daemon=True, name="wifi connect").start()

    def _connect(self, ssid, password):
        global _status
        if password is None and ssid in saved():
            ok, _, err = nmcli("con", "up", "id", ssid, timeout=45)
        else:
            args = ["dev", "wifi", "connect", ssid] + (["password", password] if password else [])
            ok, _, err = nmcli(*args, timeout=45)
        _status = (0.0, None)
        self.busy = ""
        self.message = ("CONNECTED TO %s" % ssid.upper()) if ok else "COULDN'T CONNECT: " + explain(err)
        if ok:
            for n in self.networks:
                n["active"] = n["ssid"] == ssid
                if n["ssid"] == ssid:
                    n["saved"] = True

    def forget(self, ssid):
        global _status
        ok, _, err = nmcli("con", "delete", "id", ssid, timeout=15)
        _status = (0.0, None)
        if ok:
            for n in self.networks:
                if n["ssid"] == ssid:
                    n["saved"] = n["active"] = False
        self.message = ("FORGOT %s" % ssid.upper()) if ok else "COULDN'T FORGET IT: " + explain(err)
        return ok
