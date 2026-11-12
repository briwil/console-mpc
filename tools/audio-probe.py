# Runs ON the MPC Sample (tools/audio-probe.sh sends it): everything about its sound cards that says where the inputs
# come from. Every control of every card with its value, what each card is doing right now, the USB audio settings, the
# pins. Nothing is changed.
import ctypes
import glob
import os

def show(title, path, most=200):
    try:
        text = open(path).read().rstrip()
    except Exception as ex:
        text = "(%s)" % ex
    lines = text.split("\n")
    print("=== %s  [%s]" % (title, path))
    print("\n".join(lines[:most]) + ("\n... (%d more lines)" % (len(lines) - most) if len(lines) > most else ""))

show("cards", "/proc/asound/cards")
show("pcm", "/proc/asound/pcm")
for d in sorted(glob.glob("/proc/asound/card*/pcm*/sub*")):
    for f in ("hw_params", "status"):
        show(f, os.path.join(d, f), 12)
for d in sorted(glob.glob("/proc/asound/card[0-9]*")):
    if not os.path.isdir(d):
        continue
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if os.path.isfile(p) and f not in ("id",):
            show(f, p, 40)

A = ctypes.CDLL("libasound.so.2")
P = ctypes.c_void_p
for name in ("snd_ctl_elem_id_get_name", "snd_ctl_elem_info_get_item_name", "snd_ctl_elem_iface_name", "snd_strerror",
             "snd_ctl_card_info_get_name", "snd_ctl_card_info_get_mixername", "snd_ctl_card_info_get_components"):
    getattr(A, name).restype = ctypes.c_char_p
for name in ("snd_ctl_elem_info_get_min", "snd_ctl_elem_info_get_max", "snd_ctl_elem_value_get_integer"):
    getattr(A, name).restype = ctypes.c_long
TYPES = {0: "none", 1: "switch", 2: "number", 3: "choice", 4: "bytes", 5: "iec958", 6: "number64"}

def controls(card):
    ctl = P()
    r = A.snd_ctl_open(ctypes.byref(ctl), ("hw:%d" % card).encode(), 0)
    if r < 0:
        print("=== card %d controls: can't open (%s)" % (card, A.snd_strerror(r).decode()))
        return
    ci = P()
    A.snd_ctl_card_info_malloc(ctypes.byref(ci))
    A.snd_ctl_card_info(ctl, ci)
    print("=== card %d controls  name '%s'  mixer '%s'  components '%s'" % (
        card, A.snd_ctl_card_info_get_name(ci).decode(), A.snd_ctl_card_info_get_mixername(ci).decode(),
        A.snd_ctl_card_info_get_components(ci).decode()))
    lst = P()
    A.snd_ctl_elem_list_malloc(ctypes.byref(lst))
    A.snd_ctl_elem_list(ctl, lst)
    n = A.snd_ctl_elem_list_get_count(lst)
    A.snd_ctl_elem_list_alloc_space(lst, n)
    A.snd_ctl_elem_list(ctl, lst)
    print("    %d controls" % n)
    for i in range(n):
        eid, info, val = P(), P(), P()
        A.snd_ctl_elem_id_malloc(ctypes.byref(eid))
        A.snd_ctl_elem_info_malloc(ctypes.byref(info))
        A.snd_ctl_elem_value_malloc(ctypes.byref(val))
        A.snd_ctl_elem_list_get_id(lst, i, eid)
        A.snd_ctl_elem_info_set_id(info, eid)
        if A.snd_ctl_elem_info(ctl, info) < 0:
            continue
        t = A.snd_ctl_elem_info_get_type(info)
        cnt = A.snd_ctl_elem_info_get_count(info)
        nm = A.snd_ctl_elem_id_get_name(eid).decode(errors="replace")
        iface = A.snd_ctl_elem_iface_name(A.snd_ctl_elem_id_get_interface(eid)).decode()
        A.snd_ctl_elem_value_set_id(val, eid)
        ok = A.snd_ctl_elem_read(ctl, val) >= 0
        vals, extra = [], ""
        for k in range(min(cnt, 16)):
            if not ok:
                break
            if t == 1:
                vals.append("on" if A.snd_ctl_elem_value_get_boolean(val, k) else "off")
            elif t == 2:
                vals.append(str(A.snd_ctl_elem_value_get_integer(val, k)))
            elif t == 3:
                vals.append(str(A.snd_ctl_elem_value_get_enumerated(val, k)))
            elif t == 4:
                vals.append("%02x" % (A.snd_ctl_elem_value_get_byte(val, k) & 255))
        if t == 2:
            extra = "  range %d..%d" % (A.snd_ctl_elem_info_get_min(info), A.snd_ctl_elem_info_get_max(info))
        if t == 3:
            items = []
            for k in range(min(A.snd_ctl_elem_info_get_items(info), 40)):
                A.snd_ctl_elem_info_set_item(info, k)
                A.snd_ctl_elem_info(ctl, info)
                items.append("%d=%s" % (k, A.snd_ctl_elem_info_get_item_name(info).decode(errors="replace")))
            extra = "  choices: " + ", ".join(items)
        print("    [%s] '%s' index %d  %s x%d = %s%s" % (iface, nm, A.snd_ctl_elem_id_get_index(eid), TYPES.get(t, t), cnt,
                                                       ",".join(vals) if ok else "(can't read)", extra))
    A.snd_ctl_close(ctl)

for c in range(8):
    if os.path.isdir("/proc/asound/card%d" % c):
        try:
            controls(c)
        except Exception as ex:
            print("=== card %d controls failed: %s" % (c, ex))

print("=== USB audio settings")
for d in glob.glob("/sys/kernel/config/usb_gadget/*/functions/*"):
    print("  " + d)
    try:
        if "uac" in d.lower() or "audio" in d.lower():
            for f in sorted(os.listdir(d)):
                try:
                    print("    %s = %s" % (f, open(os.path.join(d, f)).read().strip()))
                except Exception:
                    pass
    except Exception as ex:
        print("    (%s)" % ex)
for d in glob.glob("/sys/kernel/config/usb_gadget/*"):
    for f in ("UDC", "idVendor", "idProduct"):
        try:
            print("  %s %s = %s" % (d, f, open(os.path.join(d, f)).read().strip()))
        except Exception:
            pass
try:
    if not os.path.exists("/sys/kernel/debug/gpio"):
        os.system("mount -t debugfs none /sys/kernel/debug 2>/dev/null")     # (only makes the kernel's own status files readable)
except Exception:
    pass
show("pins", "/sys/kernel/debug/gpio", 400)
for d in sorted(glob.glob("/sys/kernel/debug/asoc/*")) + sorted(glob.glob("/sys/kernel/debug/asoc/*/*")):
    if os.path.isfile(d):
        show("asoc", d, 60)
for d in sorted(glob.glob("/sys/kernel/debug/regmap/*")):
    for f in ("name", "registers"):
        if os.path.isfile(os.path.join(d, f)):
            show("regmap " + f, os.path.join(d, f), 80)
for d in sorted(glob.glob("/sys/class/gpio/gpio[0-9]*")):
    try:
        print("  %s direction %s value %s" % (d, open(d + "/direction").read().strip(), open(d + "/value").read().strip()))
    except Exception:
        pass
show("pin functions", "/sys/kernel/debug/pinctrl/pinctrl-handles", 200)
print("=== who has the sound devices open")
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        fds = [os.readlink("/proc/%s/fd/%s" % (pid, f)) for f in os.listdir("/proc/%s/fd" % pid)]
        snd = sorted({f for f in fds if "/dev/snd" in f})
        if snd:
            print("  %s (%s): %s" % (open("/proc/%s/comm" % pid).read().strip(), pid, " ".join(snd)))
    except Exception:
        pass
print("=== input devices (jack switches?)")
show("input", "/proc/bus/input/devices", 200)
