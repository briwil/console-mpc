"""SF2 SYNTH finds its soundfonts in its own soundfonts/ folder. This links the .sf2 files from the SD card's sf2 folder and from the
sample folders into it when Console starts (links, not copies: the files stay where they are)."""
import os

C = os.environ.get("CONSOLE_HOME", "/data/UserData/console")
DIRS = ["/media/sample/sf2", "/media/sample/SF2", "/media/sample/Soundfonts", "/media/sample", "/data/UserData/UserLibrary/Samples",
        os.path.join(C, "samples")]


def sync(dest=None, dirs=None):
    dest = dest or os.path.join(C, "pi-app", "schwung", "modules", "sf2", "soundfonts")
    if not os.path.isdir(dest):
        return 0
    found = {}
    for d in (dirs or DIRS):
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
