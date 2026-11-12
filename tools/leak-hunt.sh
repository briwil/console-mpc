#!/bin/sh
# Which instrument or insert effect keeps memory (mpcui/leakhunt.py), from your Mac:
#   sh leak-hunt.sh        ask for it: Console is stopped, the startup menu comes up, PAD 1 starts it, about 25 minutes
#   sh leak-hunt.sh get    the report so far
KEY=${MPC_CLIENT_KEY:-$HOME/.ssh/mpc_sample_client_ed25519}
C=/data/UserData/console
mpc() { ssh -p 2222 -i "$KEY" -o ConnectTimeout=8 root@192.168.155.1 "$@"; }
mpc true || { echo "Can't reach the MPC (cable, fully started?)."; exit 1; }
if [ "${1:-}" = get ]; then
  mpc "cat $C/leak-report.txt 2>/dev/null || echo '(it has not run yet)'"
  exit 0
fi
mpc "rm -f $C/leak-report.txt; touch $C/leakhunt; sync"
# Console running: ask it to save and quit, then bring the startup menu up (as push-bridge.sh does). No power-off needed.
mpc "if pgrep -f mpc_app.py >/dev/null 2>&1; then touch $C/STOP; for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do pgrep -f mpc-console.sh >/dev/null 2>&1 || break; sleep 1; done; fi; rm -f $C/boot-attempt /run/console-boot.done; sync; systemd-run --unit=console-boot-job-\$\$ --collect --no-block /bin/sh $C/mpc/boot.sh >/dev/null 2>&1" \
  || echo "Could not bring the startup menu up: power the MPC off and on instead."
echo "Asked. The startup menu comes up on the MPC in a few seconds: press PAD 1. It runs for about 25 minutes (leave the"
echo "controls alone), then Console starts again as normal. After that run:  sh ~/leak-hunt.sh get"
