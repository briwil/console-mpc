#!/bin/sh
# What the MPC Sample's sound cards are set to right now, saved to your Desktop (nothing on the MPC is changed):
#   sh audio-probe.sh mic       with the stock MPC app recording from the built-in mic
#   sh audio-probe.sh line      ... from the jacks on the back
#   sh audio-probe.sh usb       ... from USB
# (any word: it only names the file, audio-probe-<word>.txt). Comparing the files shows what picks the input.
KEY=${MPC_CLIENT_KEY:-$HOME/.ssh/mpc_sample_client_ed25519}
C=/data/UserData/console
W=${1:-now}
HERE=$(cd "$(dirname "$0")" && pwd)
[ -f "$HERE/audio-probe.py" ] || { echo "audio-probe.py should be next to this script."; exit 1; }
OUT="$HOME/Desktop/audio-probe-$W.txt"
ssh -p 2222 -i "$KEY" -o ConnectTimeout=8 root@192.168.155.1 "$C/python/bin/python3 -" < "$HERE/audio-probe.py" > "$OUT" 2>&1 \
  || { echo "Something went wrong: see $OUT"; exit 1; }
echo "Saved $OUT ($(wc -l < "$OUT" | tr -d ' ') lines)."
