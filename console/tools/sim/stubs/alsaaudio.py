# alsaaudio stand-in for testing without audio hardware: reads give silence in real time, writes are kept in PCM.writes
import time, numpy as np
PCM_CAPTURE, PCM_PLAYBACK, PCM_NORMAL = 1, 0, 0
PCM_FORMAT_S32_LE, PCM_FORMAT_S16_LE, PCM_FORMAT_S24_3LE = 10, 2, 32
opened=[]; capture_devices=set(); RATES={}   # RATES: device -> forced rate (like a device that only does 48k)
class PCM:
    def __init__(s, type, mode, device, rate, channels, format, periodsize, periods):
        s.type=type; s.ch=channels; s.ps=periodsize; s.device=device; s.rate=RATES.get(device, rate); s.fmt=format
        s.writes=[]; s.closed=False; opened.append(s)
        if type==PCM_CAPTURE: capture_devices.add(device)
        s.t=time.perf_counter()
    def info(s): return {"rate": s.rate}
    def read(s):
        s.t+=s.ps/s.rate; d=s.t-time.perf_counter()
        if d>0: time.sleep(d)
        w={10:4,2:2,32:3}.get(s.fmt,4)
        return s.ps, bytes(s.ps*s.ch*w)
    def write(s,d):
        s.writes.append(d)
        if s.device not in capture_devices:
            frames=len(d)//(2*s.ch if s.fmt==2 else 4*s.ch)
            s.t+=frames/s.rate; dd=s.t-time.perf_counter()
            if dd>0: time.sleep(dd)
        return len(d)
    def close(s): s.closed=True
