"""SF2 SYNTH finds its soundfonts in its own soundfonts/ folder. This links the .sf2 files from the SD card's sf2 folder and from the
sample folders into it when Console starts (links, not copies: the files stay where they are)."""
import os

C = os.environ.get("CONSOLE_HOME", "/data/UserData/console")


def sd_root():
    """The SD card's mount point, whatever the card is called (/media/sample, /media/SAMPLE ...), or None."""
    try:
        rows = [l.split() for l in open(os.environ.get("CONSOLE_MOUNTS", "/proc/mounts"))]
    except OSError:
        return None
    for want in (lambda d, m: d.startswith("/dev/mmcblk1p"), lambda d, m: d.startswith("/dev/") and m.startswith("/media/")):
        for r in rows:
            if len(r) > 1 and want(r[0], r[1]):
                return r[1].replace("\\040", " ")
    return None


def default_dirs():
    sd = sd_root()
    out = [os.path.join(sd, x) for x in ("sf2", "SF2", "Soundfonts")] + [sd] if sd else []
    return out + ["/data/UserData/UserLibrary/Samples", os.path.join(C, "samples")]


def sync(dest=None, dirs=None):
    dest = dest or os.path.join(C, "pi-app", "schwung", "modules", "sf2", "soundfonts")
    if not os.path.isdir(dest):
        return 0
    found = {}
    for d in (dirs or default_dirs()):
        for root, subs, names in os.walk(d):
            subs[:] = [x for x in subs if not x.startswith(".") and x.lower() not in ("autorun",)]
            for n in names:
                if n.lower().endswith(".sf2") and not n.startswith("."):
                    found.setdefault(n, os.path.join(root, n))
    for n in os.listdir(dest):                                   # links whose file has gone
        p = os.path.join(dest, n)
        if os.path.islink(p) and not os.path.exists(p):
            os.remove(p)
    made = 0
    for n, src in found.items():
        link = os.path.join(dest, n)
        if os.path.lexists(link):
            continue
        try:
            os.symlink(src, link)
            made += 1
        except OSError:
            pass
    return made
