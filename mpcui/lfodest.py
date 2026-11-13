"""The LFO's DEST setting names the drum: "SNR DECAY" instead of just "DECAY" (a drum machine has the same setting on
several drums, and the list alone doesn't say which is which). A sampler already says "D3 LEVEL" (Console's own)."""
import re

VOWELS = set("AEIOU")


def short_name(name, size=3):
    """SNARE -> SNR, KICK -> KCK, CLAP -> CLP, CLOSED HAT -> CH, PAD 3 -> P3 (short names stay as they are)."""
    n = re.sub(r"[^A-Z0-9 ]", "", str(name).upper()).strip()
    words = n.split()
    if not words:
        return ""
    if len(n.replace(" ", "")) <= size:
        return n.replace(" ", "")
    if len(words) > 1:                                   # initials: CLOSED HAT -> CH, LOW TOM -> LT, PAD 12 -> P12
        return "".join(w[0] if not w.isdigit() else w for w in words)[:size]
    w = words[0]
    out = w[0] + "".join(c for c in w[1:] if c not in VOWELS)      # first letter, then the consonants
    if len(out) < size:                                  # (too few: back to the plain first letters)
        out = w[:size]
    return out[:size]


def abbreviations(names):
    """One short name per drum, all different (a clash gets the drum's number)."""
    out = [short_name(n) for n in names]
    for i, s in enumerate(out):
        if not s or out.count(s) > 1:
            out[i] = (s[:2] + str(i + 1))[:3] if s else str(i + 1)
    return out


_cache = {}


def install(movelfo, lfo):
    orig = movelfo.MoveLFO.values

    def values(self):
        out = orig(self)
        try:
            d = self.T.engine.drums
            l = self.cur()
            dest = l["dest"]
            if (0 <= dest < lfo.INSERT_DEST and dest < getattr(d, "param_count", 0) and getattr(d, "id", "") != "sampler"):
                voice = d.params[dest].get("voice")
                names = tuple(getattr(d, "names", None) or getattr(d, "lane_names", None) or ())
                if voice is not None and voice < len(names) and len(names) > 1:
                    ab = _cache.get(names)
                    if ab is None:
                        ab = _cache[names] = abbreviations(names)
                    out = list(out)
                    out[0] = ("DEST", ("%s %s" % (ab[voice], d.label(dest)))[:12])
        except Exception:
            pass
        return out
    movelfo.MoveLFO.values = values
