# pygame stand-in for testing without a screen: draws with Pillow, and each Surface keeps its picture in .img (save it with surface.img.save("x.png"))
import types
from PIL import Image, ImageDraw, ImageFont
FULLSCREEN=1; SRCALPHA=2; KEYDOWN=3; QUIT=4; KMOD_SHIFT=1
for i,n in enumerate("SPACE r LEFT RIGHT q ESCAPE g i e EQUALS PLUS KP_PLUS MINUS KP_MINUS LEFTBRACKET RIGHTBRACKET".split()): globals()['K_'+n]=1000+i
for i in range(1,10): globals()['K_%d'%i]=48+i
class Rect(tuple):
    def __new__(c,x,y,w,h): return tuple.__new__(c,(x,y,w,h))
    x=property(lambda s:s[0]); y=property(lambda s:s[1]); w=property(lambda s:s[2]); h=property(lambda s:s[3])
    centerx=property(lambda s:s[0]+s[2]//2); centery=property(lambda s:s[1]+s[3]//2)
class Surface:
    def __init__(s,size,flags=0,img=None):
        s.img=img or Image.new("RGBA",tuple(int(v) for v in size),(0,0,0,0 if flags&SRCALPHA else 255)); s.clip=None
    def get_size(s): return s.img.size
    def get_width(s): return s.img.size[0]
    def get_height(s): return s.img.size[1]
    def get_rect(s,center=(0,0)):
        w,h=s.img.size; return (center[0]-w//2,center[1]-h//2)
    def get_clip(s): return s.clip
    def get_bounding_rect(s):
        b=s.img.getbbox() or (0,0,0,0); return Rect(b[0],b[1],b[2]-b[0],b[3]-b[1])
    def set_clip(s,r): s.clip=r
    def _d(s): return ImageDraw.Draw(s.img)
    def _cl(s,x,y,w,h):
        if not s.clip: return x,y,w,h
        cx,cy,cw,ch=s.clip
        x2,y2=max(x,cx),max(y,cy); x3,y3=min(x+w,cx+cw),min(y+h,cy+ch)
        return x2,y2,x3-x2,y3-y2
    def fill(s,c,r=None):
        c=tuple(c)+((255,) if len(c)==3 else ())
        if r is None: s.img.paste(c,(0,0)+s.img.size)
        else:
            x,y,w,h=s._cl(*r)
            if w>0 and h>0: s._d().rectangle([x,y,x+w-1,y+h-1],fill=c)
    def blit(s,o,p):
        if s.clip:
            x,y=int(p[0]),int(p[1]); w,h=o.img.size
            x2,y2,w2,h2=s._cl(x,y,w,h)
            if w2<=0 or h2<=0: return
            o=Surface(None,img=o.img.crop((x2-x,y2-y,x2-x+w2,y2-y+h2))); p=(x2,y2)
        s.img.alpha_composite(o.img,(int(p[0]),int(p[1]))) if p[0]>=0 and p[1]>=0 else s.img.paste(o.img,(int(p[0]),int(p[1])),o.img)
def _rect(surf,col,r,w=0,br=0,border_radius=None,**corners):
    br=border_radius if border_radius is not None else br
    kw={}
    if corners:
        get=lambda k: corners.get(k, br) or 0
        cs=(get("border_top_left_radius"),get("border_top_right_radius"),get("border_bottom_right_radius"),get("border_bottom_left_radius"))
        br=max(cs); kw={"corners":tuple(bool(c) for c in cs)}
    x,y,ww,h=r
    if surf.clip:
        cx,cy,cw,ch=surf.clip
        if y+h<=cy or y>=cy+ch or x+ww<=cx or x>=cx+cw: return
    if ww<=0 or h<=0: return
    c=tuple(col)
    surf._d().rounded_rectangle([x,y,x+ww-1,y+h-1],radius=min(br,(h-1)//2,(ww-1)//2),fill=c if w==0 else None,outline=None if w==0 else c,width=w or 1,**kw)
def _line(surf,col,a,b,w):
    if surf.clip:
        cx,cy,cw,ch=surf.clip
        if not (cx<=a[0]<cx+cw): return
    surf._d().line([a,b],fill=tuple(col),width=w)
def _circle(surf,col,c,r,w=0):
    if surf.clip and not (surf.clip[1]<=c[1]<surf.clip[1]+surf.clip[3]): return
    surf._d().ellipse([c[0]-r,c[1]-r,c[0]+r,c[1]+r],fill=tuple(col) if w==0 else None,outline=None if w==0 else tuple(col),width=w or 1)
def _poly(surf,col,pts,w=0):
    if surf.clip:
        cx,cy,cw,ch=surf.clip
        if not all(cx<=p[0]<cx+cw and cy<=p[1]<cy+ch for p in pts): return
    surf._d().polygon(pts,fill=tuple(col))
draw=types.SimpleNamespace(rect=_rect,line=_line,circle=_circle,polygon=_poly)
class Font:
    def __init__(s,path,size): s.f=ImageFont.truetype(path,size); s.pt=size
    def size(s,t):
        asc,desc=s.f.getmetrics(); return (int(s.f.getlength(t)), asc+desc)
    def get_height(s):
        asc,desc=s.f.getmetrics(); return asc+desc
    def get_ascent(s): return s.f.getmetrics()[0]
    def render(s,t,aa,c):
        l,tp,r,b=s.f.getbbox(t); asc,desc=s.f.getmetrics()
        im=Image.new("RGBA",(max(1,r),asc+desc),(0,0,0,0)); ImageDraw.Draw(im).text((0,0),t,font=s.f,fill=tuple(c)); return Surface(None,img=im)
font=types.SimpleNamespace(Font=Font,init=lambda:None)
transform=types.SimpleNamespace(rotate=lambda s,a: Surface(None,img=s.img.rotate(a,expand=True)),smoothscale=lambda s,size:Surface(None,img=s.img.resize(size)))
def init(): pass
image=types.SimpleNamespace(save=lambda surf,path: surf.img.convert("RGB").save(path))
