import sys, time
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "mpcui"))
import metronome as M
M.PATH = "/tmp/ci-metro"; M.SAVE = "/tmp/ci-metro.json"
class E:
    recording = playing = False; bpm = 600.0
    def bar_beats(self): return 4
    def set_recording(self, on): self.recording = on; self.playing = on or self.playing
class T:
    engine = E(); seq_page = False; fx_page = False
    def say(self, *a): pass
M.STATE["count"] = 1
M._patch(E)
t = T(); e = t.engine
e.set_recording(True)
assert not e.recording and M.CI["active"], "count started"
for _ in range(40):
    M.tick(t); time.sleep(0.02)
assert e.recording and not M.CI["active"], "recording started after the bars"
e.recording = e.playing = False
M.STATE["count"] = 2; e.set_recording(True); e.set_recording(True)
assert not e.recording and not M.CI["active"], "second press cancels"
M.STATE["count"] = 0; e.set_recording(True); assert e.recording
print("count-in ok")
