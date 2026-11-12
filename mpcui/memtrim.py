"""Gives freed memory back to the system.

The stress test showed Console's memory climbing to ~800 MB while only ~600 MB was really in use: the rest was memory
Python had freed but the C library kept ("held free", 460 MB at the end of 2 hours). malloc_trim(0) hands it back.
It is done after a project is opened or a new one is started (everything from the old project is gone then), and every
2 minutes in the background."""
import ctypes
import gc
import threading
import time

EVERY = 120.0                 # seconds between background trims
released = [0]                # bytes the system got back so far (sum of how much memory shrank by each trim)
count = [0]
_lock = threading.Lock()
_libc = [None]


def _rss():
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def trim(collect=False):
    """malloc_trim(0). Returns the bytes memory shrank by (0 if it can't)."""
    if not _lock.acquire(False):
        return 0
    try:
        if _libc[0] is None:
            _libc[0] = ctypes.CDLL(None)
            _libc[0].malloc_trim.argtypes = [ctypes.c_size_t]
        if collect:
            gc.collect()
        before = _rss()
        _libc[0].malloc_trim(0)
        got = max(0, before - _rss())
        released[0] += got
        count[0] += 1
        return got
    except Exception:                                        # noqa: BLE001
        return 0
    finally:
        _lock.release()


def _loop():
    while True:
        time.sleep(EVERY)
        trim()


def install(audio_mod):
    E = audio_mod.Engine
    for name in ("new_song", "open_song"):
        orig = getattr(E, name, None)
        if orig is None:
            continue

        def make(orig):
            def wrapped(self, *a, **k):
                r = orig(self, *a, **k)
                trim(collect=True)
                return r
            return wrapped
        setattr(E, name, make(orig))
    threading.Thread(target=_loop, daemon=True, name="memtrim").start()
