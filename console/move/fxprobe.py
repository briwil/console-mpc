"""Tries every insert effect on its own, each in a separate process, so one that crashes can't take the others
(or Console) with it. For each effect: start it, run sound through it while its knobs move, close it; start
and close it a few more times; then two copies at once. Prints which ones crash, and where.

    ssh -i ~/.ssh/move_key ableton@move.local "python3 /data/UserData/console/move/fxprobe.py"

(Console can keep running: this doesn't use the sound.) Takes a few minutes. Just one: add its name, e.g.
fxprobe.py structor. The instruments: fxprobe.py instruments (or fxprobe.py instruments surge). As in the stress
test, everything in one process (and which instrument brings a crash on): fxprobe.py together.
"""
import os
import random
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "pi-app")
sys.path[:0] = [os.path.join(APP, "schwung"), APP]
BLOCK = 128


def one(fx_id):
    """In the child process: put one effect through its paces, saying each stage as it starts."""
    import ctypes
    import numpy as np
    import catalog
    import insertfx
    index = 1 + [f["id"] for f in catalog.FX].index(fx_id)
    lib = insertfx.Insert()._lib()
    if lib is None:
        print("NO HOST LIBRARY")
        return 2
    rng = np.random.default_rng(1)
    fp = ctypes.POINTER(ctypes.c_float)

    def stage(s):
        print("stage: " + s, flush=True)

    def run(ins, blocks, knobs=True):
        for b in range(blocks):
            left = (rng.standard_normal(BLOCK) * 0.2).astype(np.float32)
            right = left.copy()
            lib.sh_fx_process(ins.h, left.ctypes.data_as(fp), right.ctypes.data_as(fp), BLOCK)
            if not np.all(np.isfinite(left)):
                print("note: it put out NaN / infinity", flush=True)
            if knobs and b % 20 == 0 and ins.params:
                ins.knob(random.randrange(len(ins.params)), random.choice((-5, -1, 1, 5)))

    stage("starting")
    a = insertfx.Insert(None, 0, 0)
    a.choose(index)
    if not a.h:
        print("couldn't start: %s" % a.error, flush=True)
        return 3
    stage("sound through it, knobs moving")
    run(a, 1500)
    stage("its settings read back")
    for p in a.params:
        a.text(a.params.index(p))
    stage("closing")
    a.choose(0)
    for k in range(3):
        stage("starting again (%d)" % (k + 2))
        a.choose(index)
        run(a, 100)
        stage("closing again (%d)" % (k + 2))
        a.choose(0)
    stage("knobs turned while sound runs at the same time (as in Console)")
    import threading
    a.choose(index)
    go = [True]

    def sound():
        while go[0]:
            run(a, 1, knobs=False)
    th = threading.Thread(target=sound)
    th.start()
    end = time.time() + 5
    while time.time() < end and a.params:
        k = random.randrange(len(a.params))
        a.knob(k, random.choice((-40, -5, -1, 1, 5, 40)))          # (big jumps too: ends of the range)
        time.sleep(0.0005)
    go[0] = False
    th.join()
    a.choose(0)
    stage("two at once")
    a.choose(index)
    b = insertfx.Insert(None, 1, 0)
    b.choose(index)
    run(a, 200)
    run(b, 200)
    stage("closing the first of two")
    a.choose(0)
    run(b, 200)
    stage("closing the second")
    b.choose(0)
    stage("after closing: the memory checked")
    junk = [bytearray(n) for n in range(1, 40000, 37)]          # lots of allocating and freeing, so a damaged
    del junk                                                     # heap shows itself here
    import gc
    gc.collect()
    stage("done")
    return 0


def one_inst(mid):
    """In the child process: an instrument started, played (notes / drum hits) while its settings move,
    from the same thread and from another one at the same time."""
    import threading
    import drums

    def stage(s):
        print("stage: " + s, flush=True)
    stage("starting")
    d = drums.Drums("lxr")
    m = d.get(mid)
    if m is None:
        print("couldn't start", flush=True)
        return 3
    try:
        params = [p for _n, ps in m.pages(0) for p in ps]
    except Exception:                                    # noqa: BLE001
        params = []
    synth = hasattr(m, "note_on")

    def play(blocks, knobs=True):
        for b in range(blocks):
            if b % 8 == 0:
                if synth:
                    n = random.randrange(36, 84)
                    m.note_on(n, random.randint(30, 127))
                    if b % 16 == 0:
                        m.note_off(n)
                else:
                    m.hit(random.randrange(max(1, getattr(m, "lanes", 8))), random.randint(30, 127))
            m.render(BLOCK)
            if knobs and params and b % 10 == 0:
                twist()

    def twist():
        p = random.choice(params)
        try:
            v = m.stepped(p, m.get_param(p), random.choice((-40, -3, 3, 40)))
            print("set %s = %s" % (m.label(p), m.value_text(p, v) if hasattr(m, "value_text") else v), flush=True)
            m.set_param(p, v)
        except Exception:                                # noqa: BLE001
            pass
    stage("playing, settings moving")
    play(1500)
    stage("playing while settings move from another thread (as in Console)")
    go = [True]

    def sound():
        while go[0]:
            play(1, knobs=False)
    th = threading.Thread(target=sound)
    th.start()
    end = time.time() + 4
    while time.time() < end and params:
        twist()
        time.sleep(0.0005)
    go[0] = False
    th.join()
    if hasattr(m, "all_off"):
        m.all_off()
    play(100, knobs=False)
    stage("after: the memory checked")
    junk = [bytearray(n) for n in range(1, 40000, 37)]
    del junk
    import gc
    gc.collect()
    time.sleep(1)                                        # (its own threads, if it has any, keep going a moment)
    stage("done")
    return 0


def sweep(mid, key, mode=""):
    """fxprobe.py sweep noisemaker voices: what the module says about one setting, then every value of it in
    turn while notes play (in a child process: a crash shows the value it was on)."""
    if os.environ.get("FXPROBE_CHILD") != "1":
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "sweep", mid, key] + ([mode] if mode else []),
                           env=dict(os.environ, FXPROBE_CHILD="1"), capture_output=True, text=True, timeout=300)
        out = (r.stdout + r.stderr).strip()
        print(out)
        if r.returncode:
            print("\nCRASHED (%s) on the last value above" % (_signame(-r.returncode) if r.returncode < 0 else r.returncode))
        return
    import json
    import numpy as np
    import catalog
    import modules
    folder = os.path.join(modules.MODULES_DIR, mid)
    inst = modules.Instance(os.path.join(folder, "dsp.so"), folder, {})
    chain = json.loads(inst.get("chain_params", big=True) or "[]")
    entry = next((c for c in chain if c.get("key") == key), None)
    print("chain_params entry: %s" % json.dumps(entry))
    print("its value now: %r" % inst.get(key), flush=True)
    if entry and entry.get("options"):
        values = list(entry["options"]) + list(range(len(entry["options"])))
    else:
        lo, hi = (entry or {}).get("min", 0), (entry or {}).get("max", 16)
        step = (entry or {}).get("step") or (1 if entry and entry.get("type") == "int" else (hi - lo) / 16.0)
        values, v = [], lo - step
        while v <= hi + step + 1e-9:
            values.append(round(v, 4))
            v += step
    out = np.zeros((128, 2), np.float32)
    # mode "held": notes still sounding as it changes (as when you turn the knob while playing);
    # "quiet": the same, but every note let go just before (what Console could do for this setting)
    print("(mode: %s)" % (mode or "notes let go between"), flush=True)
    for rnd in range(3 if mode else 1):
        for v in (values if rnd % 2 == 0 else values[::-1]):
            print("value %s ..." % v, end=" ", flush=True)
            if mode:
                for n in range(48, 54):
                    inst.midi(0x90, n, 100)                  # a chord held
                inst.render(out)
            if mode == "quiet":
                inst.midi(0xB0, 123, 0)
                for n in range(128):
                    inst.midi(0x80, n, 0)
            inst.set(key, v)
            for b in range(60):
                if b % 6 == 0:
                    inst.midi(0x90, 48 + b % 24, 100)
                if b % 6 == 3 and not mode:
                    inst.midi(0x80, 48 + (b - 3) % 24, 0)
                inst.render(out)
            if mode:
                for n in range(128):
                    if n % 3 == 0:
                        inst.midi(0x80, n, 0)
            print("ok (it says %r)" % inst.get(key), flush=True)


SKIP_FX = set(x for x in os.environ.get("FXPROBE_SKIP", "").split(",") if x)
ONLY_FX = set(x for x in os.environ.get("FXPROBE_ONLY", "").split(",") if x)     # (narrowing down: just these)


def together_child(inst_ids, rounds, seed):
    """In one process, as in Console: these instruments started (and played a little), then every insert
    effect in turn with a second one beside it, sound going through them."""
    import ctypes
    import numpy as np
    import catalog
    import drums
    import insertfx
    rng = random.Random(seed)
    d = drums.Drums("lxr")
    keep = []
    for mid in inst_ids:
        print("stage: starting instrument %s" % mid, flush=True)
        m = d.get(mid)
        if m is None:
            continue
        keep.append(m)
        for b in range(40):
            if b % 8 == 0:
                (m.note_on(60, 100) if hasattr(m, "note_on") else m.hit(0, 100))
            m.render(BLOCK)
        if hasattr(m, "all_off"):
            m.all_off()
            m.render(BLOCK)
    lib = insertfx.Insert()._lib()
    fp = ctypes.POINTER(ctypes.c_float)
    a, b = insertfx.Insert(None, 0, 0), insertfx.Insert(None, 0, 1)
    n = len(catalog.FX)
    ids = [f["id"] for f in catalog.FX]
    if ONLY_FX:
        rounds = max(rounds, 70 // max(1, len(ONLY_FX)))      # (a few effects: round more times)
    others = []                                  # (like your song: TAPESCAM and JUNOLOGUE on other instruments)
    for k, fx in enumerate(("tapescam", "tapescam", "junologue-chorus")):
        if fx in ids:
            o = insertfx.Insert(None, 1 + k, 0)
            o.choose(1 + ids.index(fx))
            others.append(o)
    for r in range(rounds):
        for i in range(1, n + 1):
            j = rng.randrange(n + 1)
            if ids[i - 1] in SKIP_FX or (ONLY_FX and ids[i - 1] not in ONLY_FX):
                continue
            if ONLY_FX:
                pool = [k + 1 for k, x in enumerate(ids) if x in ONLY_FX]
                j = rng.choice(pool + [0])
            if j and ids[j - 1] in SKIP_FX:
                j = 0
            na, nb = ids[i - 1], (ids[j - 1] if j else "none")
            print("stage: closing %s, starting %s (insert 1)" % (ids[a.index - 1] if a.index else "none", na), flush=True)
            a.choose(i)
            print("stage: closing %s, starting %s (insert 2)" % (ids[b.index - 1] if b.index else "none", nb), flush=True)
            b.choose(j)
            print("stage: sound through %s + %s" % (na, nb), flush=True)
            for k in range(150):
                left = (np.random.standard_normal(BLOCK) * 0.2).astype(np.float32)
                right = left.copy()
                for ins in [a, b] + others:
                    if ins.h:
                        lib.sh_fx_process(ins.h, left.ctypes.data_as(fp), right.ctypes.data_as(fp), BLOCK)
                if k % 30 == 0:
                    for ins in (a, b):
                        if ins.params:
                            ins.knob(rng.randrange(len(ins.params)), rng.choice((-3, 3)))
    a.choose(0)
    b.choose(0)
    print("stage: done", flush=True)
    return 0


SKIP_FX_ARG = set()


def together(env):
    """fxprobe.py together: is it a mix that crashes (as in the stress test), and which instrument brings it on?
    Tries the effects alone, then with every instrument started first, then narrows the instruments down."""
    import drums
    allinst = [mid for mid, _ in drums.available_machines()]
    tries = [0]

    def crashes(ids, label):
        for attempt in range(2):
            tries[0] += 1
            t = time.time()
            try:
                r = subprocess.run([sys.executable, os.path.abspath(__file__), "--together", ",".join(ids), "2",
                                    str(attempt + 1)], capture_output=True, text=True, timeout=600, env=env)
                out, code = (r.stdout + r.stderr).strip().splitlines(), r.returncode
            except subprocess.TimeoutExpired:
                out, code = [], "hung"
            stages = [l[7:] for l in out if l.startswith("stage: ")]
            if code != 0:
                why = "FROZE" if code == "hung" else "CRASHED (%s)" % (_signame(-code) if isinstance(code, int)
                                                                     and code < 0 else code)
                print("  %-44s %s, while: %s" % (label, why, stages[-1] if stages else "?"), flush=True)
                for l in [x for x in out if not x.startswith(("stage: ", "insert effect:", "instrument:"))][-3:]:
                    print("        " + l[:150])
                return True
        print("  %-44s ok (%.0f s)" % (label, time.time() - t), flush=True)
        return False

    print("Effects one after another in one process, as in the stress test (memory checks on)...\n", flush=True)
    if crashes([], "effects only, no instruments"):
        print("\nIt's among the effects themselves (no instrument needed). Narrowing them down...\n", flush=True)
        import catalog
        group = [f["id"] for f in catalog.FX if f["id"] not in SKIP_FX_ARG]
        while len(group) > 1 and tries[0] < 60:
            half = len(group) // 2
            found = None
            for part in (group[:half], group[half:]):
                env["FXPROBE_ONLY"] = ",".join(part)
                if crashes([], "effects " + _names(part)):
                    found = part
                    break
            if found is None:
                print("\nIt takes effects from both halves together: %s" % ", ".join(group))
                return
            group = found
        print("\nThe effect that crashes: %s" % ", ".join(group))
        return
    if not crashes(allinst, "after all %d instruments" % len(allinst)):
        print("\nNo crash this way: send this to Claude.")
        return
    group = allinst
    while len(group) > 1 and tries[0] < 40:
        half = len(group) // 2
        first, second = group[:half], group[half:]
        if crashes(first, "after " + _names(first)):
            group = first
        elif crashes(second, "after " + _names(second)):
            group = second
        else:
            print("\nIt takes instruments from both halves together: %s" % ", ".join(group))
            return
    print("\nThe instrument that brings it on: %s" % ", ".join(group))


def _names(ids):
    return ", ".join(ids) if len(ids) <= 3 else "%s ... %s (%d)" % (ids[0], ids[-1], len(ids))


def _check_env():
    env = dict(os.environ, MALLOC_CHECK_="3", MALLOC_PERTURB_="165")
    dbg = next((p for p in ("/lib/libc_malloc_debug.so.0", "/usr/lib/libc_malloc_debug.so.0",
                            "/lib/aarch64-linux-gnu/libc_malloc_debug.so.0",
                            "/usr/lib/aarch64-linux-gnu/libc_malloc_debug.so.0",
                            "/usr/lib/x86_64-linux-gnu/libc_malloc_debug.so.0") if os.path.exists(p)), None)
    if dbg:
        env["LD_PRELOAD"] = dbg
    return env, dbg


def _signame(n):
    try:
        return signal.Signals(n).name
    except ValueError:
        return str(n)


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--one":
        sys.exit(one(sys.argv[2]))
    if len(sys.argv) > 2 and sys.argv[1] == "--inst":
        sys.exit(one_inst(sys.argv[2]))
    if len(sys.argv) > 3 and sys.argv[1] == "sweep":
        return sweep(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
    if len(sys.argv) > 4 and sys.argv[1] == "--together":
        sys.exit(together_child([x for x in sys.argv[2].split(",") if x], int(sys.argv[3]), int(sys.argv[4])))
    insts = len(sys.argv) > 1 and sys.argv[1] == "instruments"
    if insts:
        import drums
        ids = [mid for mid, _ in drums.available_machines()]
        wanted = sys.argv[2:]
    else:
        import catalog
        ids = [f["id"] for f in catalog.FX]
        wanted = sys.argv[1:]
    if wanted:
        ids = [i for i in ids if i in wanted]
    if len(sys.argv) > 1 and sys.argv[1] == "together":
        env = _check_env()[0]
        skip = [a[5:] for a in sys.argv[2:] if a.startswith("skip=")]
        if skip:
            env["FXPROBE_SKIP"] = ",".join(",".join(skip).split(","))
            SKIP_FX_ARG.update(env["FXPROBE_SKIP"].split(","))
            print("(leaving out: %s)" % env["FXPROBE_SKIP"])
        return together(env)
    bad = []
    # the C library's memory checks on in each test: an effect that writes where it shouldn't is caught (a
    # damaged heap often doesn't crash the effect that did it, only something later, somewhere else)
    env = dict(os.environ, MALLOC_CHECK_="3", MALLOC_PERTURB_="165")
    dbg = next((p for p in ("/lib/libc_malloc_debug.so.0", "/usr/lib/libc_malloc_debug.so.0",
                            "/lib/aarch64-linux-gnu/libc_malloc_debug.so.0",
                 "/usr/lib/aarch64-linux-gnu/libc_malloc_debug.so.0", "/usr/lib/x86_64-linux-gnu/libc_malloc_debug.so.0") if os.path.exists(p)), None)
    if dbg:
        env["LD_PRELOAD"] = dbg
    try:
        old_libc = tuple(int(x) for x in os.confstr("CS_GNU_LIBC_VERSION").split()[1].split(".")[:2]) < (2, 34)
    except (ValueError, OSError, IndexError):
        old_libc = False
    print("Trying %d %s, one at a time (memory checks %s)...\n" %
          (len(ids), "instruments" if insts else "insert effects", "on" if (dbg or old_libc) else "partly on"),
          flush=True)
    for fx in ids:
        t = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--inst" if insts else "--one", fx],
                               capture_output=True, text=True, timeout=90, env=env)
            out = (r.stdout + r.stderr).strip().splitlines()
            code = r.returncode
        except subprocess.TimeoutExpired as ex:
            out = ((ex.stdout or b"").decode(errors="replace") if isinstance(ex.stdout, bytes)
                   else (ex.stdout or "")).strip().splitlines()
            code = "hung"
        stages = [l[7:] for l in out if l.startswith("stage: ")]
        sets = [l for l in out if l.startswith("set ")]
        notes = [l for l in out if not l.startswith("stage: ") and l.strip() and not l.startswith("set ")
                 and not l.startswith("insert effect: starting") and not l.startswith("instrument: starting")]
        where = stages[-1] if stages else "?"
        if code == 0:
            print("  ok       %-18s (%.1f s)%s" % (fx, time.time() - t,
                                                   "   " + notes[-1] if any("NaN" in n for n in notes) else ""))
        elif code == 3:
            print("  -        %-18s %s" % (fx, " ".join(notes)[:80]))
        else:
            why = "FROZE" if code == "hung" else "CRASHED (%s)" % _signame(-code) if isinstance(code, int) and code < 0 \
                else "FAILED (exit %s)" % code
            print("  %s  %s, while: %s" % (why, fx, where), flush=True)
            for n in notes[-6:]:
                print("             " + n[:160])
            if sets:
                print("             the last settings changed: " + "; ".join(l[4:] for l in sets[-4:])[:300])
            bad.append(fx)
    print("\n%s" % ("Every one that starts is fine on its own." if not bad else
                    "Problem effects: " + ", ".join(bad)), flush=True)


if __name__ == "__main__":
    main()
