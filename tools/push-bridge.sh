#!/bin/sh
# Safe one-command update of the MPC bridge + screens from your Mac:   sh push-bridge.sh
# Why this instead of curl | ssh tar: it (1) downloads fresh (no cached old copy) and checks the file is whole,
# (2) quits Console on the MPC first so no file is replaced while it's running (that froze it),
# (3) unpacks beside the old copy, then swaps, (4) flushes to flash (sync) and (5) checks the build on the MPC
# matches what it sent. Only then does it tell you it is safe to restart.
set -eu
KEY=${MPC_CLIENT_KEY:-$HOME/.ssh/mpc_sample_client_ed25519}
HOST=root@192.168.155.1
C=/data/UserData/console
mpc() { ssh -p 2222 -i "$KEY" -o ConnectTimeout=8 "$HOST" "$@"; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

echo "1/5  Downloading the latest build"
curl -fsSL -H 'Cache-Control: no-cache' "https://github.com/briwil/console-mpc/releases/download/bridge-latest/mpc-bridge.tgz?t=$(date +%s)" -o "$T/b.tgz"
gzip -t "$T/b.tgz"
tar xzf "$T/b.tgz" -C "$T" mpc/BUILD
NEW=$(cat "$T/mpc/BUILD"); echo "     build: $NEW"

echo "2/5  Reaching the MPC and quitting Console there"
mpc true || { echo "Can't reach the MPC (cable, SD card, fully started?)."; exit 1; }
echo "     on the MPC now: $(mpc "cat $C/mpc/BUILD 2>/dev/null || echo unknown")"
mpc "touch $C/STOP"
i=0
while [ "$(mpc "ps | grep -c '[a]pp.py'")" != 0 ]; do
  i=$((i+1)); [ $i -gt 25 ] && { echo "Console won't quit. Press Shift+STOP on the MPC and run this again."; exit 1; }
  sleep 1
done

echo "3/5  Sending"
cat "$T/b.tgz" | mpc "rm -rf $C/mpc.new && mkdir -p $C/mpc.new && cd $C/mpc.new && tar xzf - && test -f mpc/BUILD && test -f mpc/libjack_mpc.so"

echo "4/5  Swapping in, then flushing to flash"
mpc "cd $C && rm -rf mpc.old && { [ -d mpc ] && mv mpc mpc.old || true; } && mv mpc.new/mpc mpc && rmdir mpc.new && sync && sleep 1 && sync"

echo "5/5  Checking"
GOT=$(mpc "cat $C/mpc/BUILD")
[ "$GOT" = "$NEW" ] || { echo "MISMATCH: MPC has '$GOT'. Do NOT restart; run this again."; exit 1; }
echo "Done: the MPC has build $GOT, safely written. Bringing up the startup menu (no restart needed)..."
# Run the power-on script again by hand, the way the power-on hook does: it waits for the stock app, takes over and shows the menu.
# (A warm "reboot" left the panel dead until a real power-off, so there is no restart here.)
mpc "rm -f $C/boot-attempt /run/console-boot.done; sync; systemd-run --unit=console-boot-update-\$\$ --collect --no-block /bin/sh $C/mpc/boot.sh >/dev/null 2>&1" \
  || echo "Could not start the menu: power the MPC off and on instead."
echo "The startup menu (PAD 1 CONSOLE / PAD 2 MPC) comes up on the MPC in a few seconds."
