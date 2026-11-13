"""The Move's sound output: a JACK client (the JACK server from RNBO Move Takeover, started by console mode).

Works like audio.OutPort, so the engine treats it the same: the engine pushes blocks in, JACK pulls 128
frames at a time out of a ring buffer from its own thread. JACK runs at the tape's rate (44100), so no
resampling. Talks to libjack directly with ctypes: nothing to install.
"""
import ctypes as c
import os
import sys

import numpy as np

LIB = os.environ.get("CONSOLE_LIBJACK", "/data/UserData/rnbo/lib/libjack.so.0")
AUDIO = b"32 bit float mono audio"
IS_OUTPUT = 2
NO_START_SERVER = 1


def available():
    return os.path.exists(LIB) or os.environ.get("CONSOLE_PLATFORM") == "move"


_PROCESS = c.CFUNCTYPE(c.c_int, c.c_uint32, c.c_void_p)
_SHUTDOWN = c.CFUNCTYPE(None, c.c_void_p)
_j = None


def _lib():
    global _j
    if _j is None:
        j = c.CDLL(LIB)
        j.jack_client_open.restype = c.c_void_p
        j.jack_port_register.restype = c.c_void_p
        j.jack_port_register.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p, c.c_ulong, c.c_ulong]
        j.jack_set_process_callback.argtypes = [c.c_void_p, _PROCESS, c.c_void_p]
        j.jack_on_shutdown.argtypes = [c.c_void_p, _SHUTDOWN, c.c_void_p]
        for f in ("jack_activate", "jack_deactivate", "jack_client_close", "jack_get_sample_rate",
                  "jack_get_buffer_size"):
            getattr(j, f).argtypes = [c.c_void_p]
        j.jack_port_get_buffer.restype = c.c_void_p
        j.jack_port_get_buffer.argtypes = [c.c_void_p, c.c_uint32]
        j.jack_connect.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p]
        _j = j
    return _j


class JackPort:
    """Same shape as audio.OutPort: push(), fill(), delay(), TARGET, gain, dead, close()."""

    TARGET = 512 * 3
    SIZE = 1 << 15                                # ring buffer frames (about 0.75 s)

    def __init__(self, rate, label="MOVE", name=b"console"):
        # the audio thread must get the interpreter quickly every 2.9 ms: hand it over more often than the
        # default 5 ms
        sys.setswitchinterval(0.001)
        self.label, self.in_rate = label, rate
        self.gain = 1.0
        self.dead = None
        self.ring = np.zeros((self.SIZE, 2), np.float32)
        self.wr = self.rd = 0                     # frames written / read so far (only ever grow)
        self.primed = False
        self.underruns = 0
        j = _lib()
        status = c.c_int()
        self.client = j.jack_client_open(name, NO_START_SERVER, c.byref(status))
        if not self.client:
            raise RuntimeError("JACK isn't running (status %d)" % status.value)
        self.rate = j.jack_get_sample_rate(self.client)
        self.jack_block = j.jack_get_buffer_size(self.client)
        if self.rate != rate:
            j.jack_client_close(self.client)
            raise RuntimeError("JACK runs at %d Hz, the tape at %d" % (self.rate, rate))
        self.ports = [j.jack_port_register(self.client, n, AUDIO, IS_OUTPUT, 0) for n in (b"out_L", b"out_R")]
        if not all(self.ports):
            j.jack_client_close(self.client)
            raise RuntimeError("couldn't make JACK ports")
        self._cb = _PROCESS(self._process)        # kept, or Python frees it while JACK still calls it
        self._down = _SHUTDOWN(self._shutdown)
        j.jack_set_process_callback(self.client, self._cb, None)
        j.jack_on_shutdown(self.client, self._down, None)
        if j.jack_activate(self.client):
            j.jack_client_close(self.client)
            raise RuntimeError("couldn't start the JACK client")
        for port, dest in ((b"out_L", b"system:playback_1"), (b"out_R", b"system:playback_2")):
            j.jack_connect(self.client, name + b":" + port, dest)

    # ---- the engine's side

    def start(self):
        pass                                      # JACK already calls us

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass

    def delay(self):
        """About how long, in tape frames, between pushing a block and hearing it."""
        return int(self.TARGET + 2 * self.jack_block)

    def fill(self):
        return self.wr - self.rd

    def push(self, block):
        x = block[:, :2] if block.shape[1] >= 2 else np.repeat(block[:, :1], 2, axis=1)
        n = len(x)
        if self.fill() + n > self.SIZE:           # JACK stalled: drop the backlog
            self.rd = self.wr - self.TARGET
        i = self.wr % self.SIZE
        k = min(n, self.SIZE - i)
        self.ring[i:i + k] = x[:k]
        if k < n:
            self.ring[:n - k] = x[k:]
        self.wr += n                              # only after the frames are in place

    def close(self):
        if self.client:
            j = _lib()
            j.jack_deactivate(self.client)
            j.jack_client_close(self.client)
            self.client = None

    # ---- JACK's side (its own thread, every 128 frames)

    def _process(self, n, arg):
        try:
            j = _j
            outs = [np.ctypeslib.as_array(c.cast(j.jack_port_get_buffer(p, n), c.POINTER(c.c_float)), (n,))
                    for p in self.ports]
            have = self.wr - self.rd
            if not self.primed:
                if have >= self.TARGET:
                    self.primed = True
                    self.rd = self.wr - self.TARGET   # start from exactly TARGET, so delay() is right
            if not self.primed or have < n:
                if self.primed:
                    self.primed = False               # ran dry: wait until there's enough again
                    self.underruns += 1
                outs[0][:] = 0.0
                outs[1][:] = 0.0
                return 0
            i = self.rd % self.SIZE
            k = min(n, self.SIZE - i)
            blk = self.ring[i:i + k] if k == n else np.concatenate([self.ring[i:], self.ring[:n - k]])
            g = self.gain
            if g != 1.0:
                blk = blk * g
                if g > 1.0:
                    blk = np.tanh(blk)                # turned up past the mix level: round off the peaks
            outs[0][:] = blk[:, 0]
            outs[1][:] = blk[:, 1]
            self.rd += n
        except Exception as e:                        # never let an error escape into JACK
            self.dead = str(e) or e.__class__.__name__
        return 0

    def _shutdown(self, arg):
        self.dead = "JACK stopped"
