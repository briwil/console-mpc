#!/bin/sh
# Takes a screenshot of the MPC's screen (the native 320x240 page Console is showing) onto your Mac's Desktop:
#   sh screenshot.sh [name]      -> ~/Desktop/console-<name>.png      (run it while the page you want is up)
set -eu
KEY=${MPC_CLIENT_KEY:-$HOME/.ssh/mpc_sample_client_ed25519}
NAME=${1:-screen}
OUT="$HOME/Desktop/console-$NAME.png"
T=$(mktemp)
ssh -p 2222 -i "$KEY" root@192.168.155.1 "cat /tmp/console-native.rgb" > "$T"
python3 - "$T" "$OUT" <<'PY'
import struct, sys, zlib
raw = open(sys.argv[1], "rb").read()
if len(raw) < 8 + 320 * 240 * 3 or raw[:4] != b"CNAT":
    sys.exit("This page has no colour screenshot (it shows the scaled Move screen). Try another page.")
px = raw[8:8 + 320 * 240 * 3]
rows = b"".join(b"\0" + px[y * 960:(y + 1) * 960] for y in range(240))
def chunk(t, d):
    c = struct.pack(">I", len(d)) + t + d
    return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 240, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
open(sys.argv[2], "wb").write(png)
print("saved", sys.argv[2])
PY
rm -f "$T"
