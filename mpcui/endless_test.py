import sys, types, time
for _m in ('pygame', 'pygame.mixer'): sys.modules.setdefault(_m, types.ModuleType(_m))
sys.path[:0] = ['mpcui', 'console/pi-app', 'console/move']
import native, endless, endlesspage as ep, notes, sequencer, pots, movelfo
endless.install_engine()
ep.install_pickers(movelfo, pots)
fails = 0
def check(c, m):
    global fails
    print(("ok:   " if c else "FAIL: ") + m)
    fails += 0 if c else 1

seq = notes.NoteSequencer()
said = []
eng = types.SimpleNamespace(slot=0, slots=["obxd"], seq=seq, drums=None, playing=False, seq_changed=lambda: None,
                            frames_per_beat=lambda: 22050.0, _heard_frame=lambda: 0)
class Off:
    def active(self): return False
T = types.SimpleNamespace(engine=eng, seq_page=True, fx_page=None, inst_page=False, song_page=False, punch=Off(), auto=Off(),
                          arp_pop=0, pads_pop=0, guitar_shown=lambda: False, synth_shown=lambda: True, octave=0,
                          say=lambda t, s=2: said.append(t), shift_held=lambda: False, message=None, message_until=0, _mpc_menu=None)
board = types.SimpleNamespace(shift=False, T=T)
check(not ep.on_page(T), "STEP: not its page")
# pick ENDLESS on ARP 2
ml = movelfo.MoveLFO(T); T.mlfo = ml
T.arp_pop = 2
ml.cfg = lambda: {"glide": 0, "bend": 0}
vals = ml.arp_values()
check(vals[-1] == ("SEQUENCER", "STEP"), "ARP 2 shows SEQUENCER")
go = pots.target(T, 3)
go(120)
check(endless.active(seq), "K3 on ARP 2 picks ENDLESS")
T.arp_pop = 0
check(ep.on_page(T), "its page is up")
# entry
ep.key(T, board, ep.RECORD, 127)
en = endless.of(seq)
check(en.entry, "SEQ RECORD: entry on")
for p in (0, 2, 4):
    ep.pad_event(T, board, p, 100)
ep.key(T, board, ep.RIGHT, 127)                 # rest
board.shift = True; ep.key(T, board, ep.PLUS, 127); board.shift = False   # tie
check([t[0] for t in en.line(seq)] == ["n", "n", "n", "r", "t"], "pads, rest, tie: %s" % en.line(seq))
ep.key(T, board, ep.LEFT, 127)
check(len(en.line(seq)) == 4, "MINUS takes the last off")
ep.key(T, board, ep.DELETE, 127)
check(len(en.line(seq)) == 4, "ERASE once: not yet")
# pots
pots.target(T, 1)(127); pots.target(T, 2)(64)
check(en.rate == len(sequencer.RATES) - 1 and en.direction == 2, "K1 / K2 by position")
en.rate = 0; en.direction = 0
# transpose while playing, entry off
ep.key(T, board, ep.RECORD, 127)
eng.playing = True
first = en.first_note(seq)
used = ep.pad_event(T, board, 7, 100)
check(used and en.transpose != 0, "a pad transposes while it plays (%+d)" % en.transpose)
ep.pad_event(T, board, 7, 0)
check(en.transpose == 0, "let go: back (HOLD off)")
en.hold = 1; ep.pad_event(T, board, 7, 100); ep.pad_event(T, board, 7, 0)
check(en.transpose != 0, "HOLD: it stays")
# draw
nat = types.SimpleNamespace(canvas=native.Canvas(), time=time, ACC=native.ACC, _pad_n=0)
eng._heard_frame = lambda: 6000
ep.draw(T, nat)
from PIL import Image
Image.fromarray(nat.canvas.px).resize((640, 480), Image.NEAREST).save("/tmp/endless.png")
# drums: PADS pop-up
dseq = sequencer.Sequencer()
eng2 = types.SimpleNamespace(slot=0, slots=["606"], seq=dseq, drums=types.SimpleNamespace(lanes=16), playing=False, seq_changed=lambda: None)
T.engine = eng2; T.synth_shown = lambda: False
ml2 = movelfo.MoveLFO(T)
check(ml2.pads_values()[-1][0] == "SEQUENCER", "PADS shows SEQUENCER on a drum machine")
for _ in range(10): ml2.pads_knob(4, 1, False)
check(endless.active(dseq), "PADS knob 4 picks ENDLESS")
en2 = endless.of(dseq); en2.entry = True
ep.pad_event(T, board, 9, 90)                  # row 1, col 1 -> lane 5
check(en2.line(dseq) == [["n", 5, 90]], "a drum pad adds its drum: %s" % en2.line(dseq))
print("FAILURES", fails)
