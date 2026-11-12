#!/bin/sh
# Which instrument or insert effect keeps memory (mpcui/leakhunt.py), from your Mac:
#   sh leak-hunt.sh        ask for it: it runs the next time Console starts (Shift + STOP, then PAD 1), about 25 minutes
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
echo "Asked. Now restart Console on the MPC (Shift + STOP, then PAD 1): it runs for about 25 minutes (leave the controls"
echo "alone), then Console starts again as normal. After that run:  sh ~/leak-hunt.sh get"
