import sys, types, time, random, ctypes
for n in ("pygame","pygame.mixer","pygame.midi"):
    sys.modules[n]=types.ModuleType(n)
import os
R=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..")
sys.path[:0]=[R+"/mpcui",R+"/console/move",R+"/console/pi-app"]
import numpy as np, native
lib=ctypes.CDLL(sys.argv[1]); f=lib.dt_blend
f.argtypes=[ctypes.c_void_p]+[ctypes.c_int]*3+[ctypes.c_int]+[ctypes.c_void_p]+[ctypes.c_int]*5
f.restype=None
random.seed(1)
items=[]
words=["SONG OFF","P1","PLAYS X2","KICK","ROW 3/5","HELLO WORLD","A","FX12","TR-808 MUTE"]
for _ in range(80):
    items.append((random.choice(words), random.randint(-30,330), random.randint(-10,250), tuple(random.randint(0,255) for _ in range(3)), random.choice([8,16,24,32,48]), random.choice([0,-1,-3])))
def run(use_c):
    native._cdraw = f if use_c else False
    c=native.canvas; c.clear((16,20,24))
    t=time.perf_counter()
    for (w,x,y,col,px,tr) in items:
        c.text_px(x,y,w,col,px,tr)
    for (w,x,y,col,px,tr) in items[:20]:
        c.text(x,y,w,col,random.choice([2,3]) if False else 2)
    dt=time.perf_counter()-t
    return c.px.copy(), dt
a,ta=run(False); b,tb=run(True)
a,ta=run(False); b,tb=run(True)   # warm masks
d=int(np.abs(a.astype(int)-b.astype(int)).max())
print("drawtext: C and numpy text differ by at most", d, "levels (numpy %.1f ms, C %.1f ms)"%(ta*1000,tb*1000))
assert d<=1
