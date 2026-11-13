#!/bin/sh
# Console for the MPC Sample. The firmware runs this when the card is in (the "autorun" feature).
# It does two things, both started as background services so the stock app's own start-up is never held up:
#   1. Console/install.sh : first time (or after an update): copies Console to the Sample's internal drive; then starts Console's
#                           startup menu (PAD 1 = Console, PAD 2 = the stock MPC app).
#   2. dev-ssh.sh         : only if the keys authorized_keys + ssh_host_ed25519_key are in the card's ConsoleDev folder, or in this
#                           folder (for developers).
# To skip Console for one start, put an empty file called NOCONSOLE on the card (next to the Console folder).
set -u
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
R=$(dirname -- "$D")

[ "$(id -u)" = 0 ] || exit 1
command -v systemd-run >/dev/null 2>&1 || exit 1

if [ -f "$R/Console/install.sh" ]; then
  systemd-run --unit=console-install --collect --no-block --property=After=ac50.service \
    /bin/sh "$R/Console/install.sh" >/dev/null 2>&1 || true
fi

# the keys: in a folder called ConsoleDev on the card (it is not part of the zip, so updating never removes it), or in this folder
KD=""
for d in "$R/ConsoleDev" "$D"; do
  if [ -s "$d/authorized_keys" ] && [ -s "$d/ssh_host_ed25519_key" ]; then KD=$d; break; fi
done
if [ -n "$KD" ] && [ -f "$D/dev-ssh.sh" ]; then
  /bin/sh "$D/dev-ssh.sh" "$KD" || true
fi
exit 0
