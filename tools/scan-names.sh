#!/bin/sh
# Every synth's preset names, read once on the MPC Sample (mpcui/namescan.py), from your Mac:
#   sh scan-names.sh        ask for the scan: it runs the next time Console starts (Shift + STOP, then PAD 1)
#   sh scan-names.sh get    how far it is; when it's done, the names are copied to your Desktop (preset-names-scan.json)
KEY=${MPC_CLIENT_KEY:-$HOME/.ssh/mpc_sample_client_ed25519}
C=/data/UserData/console
mpc() { ssh -p 2222 -i "$KEY" -o ConnectTimeout=8 root@192.168.155.1 "$@"; }
mpc true || { echo "Can't reach the MPC (cable, fully started?)."; exit 1; }
if [ "${1:-}" = get ]; then
  mpc "cat $C/preset-names-scan.txt 2>/dev/null || echo '(no scan has run yet)'"
  if mpc "grep -q '^DONE' $C/preset-names-scan.txt 2>/dev/null"; then
    OUT="$HOME/Desktop/preset-names-scan.json"
    mpc "cat $C/preset-names-scan.json" > "$OUT" && echo "The names are in $OUT: send that file to Claude."
  else
    echo "Not done yet (the MPC's screen shows how far it is). Run this again when Console has restarted."
  fi
  exit 0
fi
mpc "rm -f $C/preset-names-scan.txt $C/preset-names-scan.json; touch $C/scan-names; sync"
echo "Asked. Now restart Console on the MPC (Shift + STOP, then PAD 1): it reads the names (leave the controls alone),"
echo "then starts again as normal. After that run:  sh ~/scan-names.sh get"
