#!/bin/sh
# Audio inputs on the MPC Sample, from your Mac:
#   sh input-check.sh          what the MPC's sound card looks like right now (send the output back)
#   sh input-check.sh on       turn Console's inputs on  (the next time Console starts)
#   sh input-check.sh off      turn them off again       (if the sound breaks up with them on)
KEY=${MPC_CLIENT_KEY:-$HOME/.ssh/mpc_sample_client_ed25519}
C=/data/UserData/console
mpc() { ssh -p 2222 -i "$KEY" -o ConnectTimeout=8 root@192.168.155.1 "$@"; }
mpc true || { echo "Can't reach the MPC (cable, fully started?)."; exit 1; }
case "${1:-}" in
  on)  mpc "rm -f $C/input-status.txt; touch $C/ENABLE_INPUT; sync"; echo "Inputs ON. Restart Console (Shift + STOP, then PAD 1), try recording, then run:  sh input-check.sh"; exit 0;;
  off) mpc "rm -f $C/ENABLE_INPUT; sync"; echo "Inputs OFF. Restart Console."; exit 0;;
esac
mpc '
C=/data/UserData/console
echo "=== build: $(cat $C/mpc/BUILD 2>/dev/null)   inputs enabled: $([ -e $C/ENABLE_INPUT ] && echo yes || echo no)   data: $(cat $C/data-folder.txt 2>/dev/null)"
echo "=== running: $(ps | grep -c "[a]pp.py") console, $(ps | grep -c "[M]PC Sampl") stock app"
echo "=== input-status.txt"; cat $C/input-status.txt 2>/dev/null || echo "(none)"
echo "=== cards"; cat /proc/asound/cards
echo "=== pcm"; cat /proc/asound/pcm
for d in /proc/asound/card*/pcm*; do
  echo "--- $d"; cat $d/info 2>/dev/null | grep -E "^(id|name|stream|subdevices)"
  for s in $d/sub*; do echo "  $s: $(cat $s/status 2>/dev/null | head -n 1)"; cat $s/hw_params 2>/dev/null | sed "s/^/      /"; done
done
echo "=== mixer tools: $(which amixer tinymix alsactl arecord aplay 2>/dev/null | tr "\n" " ")"
for c in 0 1 2 3; do [ -d /proc/asound/card$c ] || continue; echo "=== card $c controls"; (amixer -c $c contents 2>/dev/null || tinymix -D $c 2>/dev/null || echo "(no mixer tool)") | head -n 150; done
echo "=== asound state files"; ls -l /var/lib/alsa/asound.state /etc/asound.conf /usr/share/alsa/ucm* 2>/dev/null
echo "=== mounts"; grep -E "media|UserData" /proc/mounts
'
