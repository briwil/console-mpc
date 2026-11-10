#!/bin/sh
# Runs at power-on (started by the hook in the SD card's autorun.sh, see install-boot.sh): shows the startup menu,
# then starts Console or the stock MPC app. It cannot lock you out of the stock app:
#   - no answer within a few seconds -> stock app
#   - a previous start that never finished (marker file) -> stock app this time
#   - a file named NOCONSOLE on the SD card, or /data/UserData/console/NOBOOT -> menu skipped
C=/data/UserData/console
M=$C/mpc
MARK=/run/console-boot.done          # /run is cleared every power-on: runs once per boot
TRY=$C/boot-attempt

[ -e "$MARK" ] && exit 0
touch "$MARK"
exec >> "$C/boot.log" 2>&1
echo "--- boot.sh $(date)"
[ -e /media/sample/NOCONSOLE ] && exit 0
[ -e "$C/NOBOOT" ] && exit 0
[ -x "$C/python/bin/python3" ] && [ -x "$M/bootmenu" ] || exit 0
if [ -e "$TRY" ]; then rm -f "$TRY"; exit 0; fi      # last time it never got through: let the stock app start
touch "$TRY"

n=0
while ! systemctl is-active --quiet ac50.service && [ $n -lt 90 ]; do sleep 1; n=$((n + 1)); done
sleep 12                                             # let the stock app finish starting (and the panel finish talking to it)
systemctl unset-environment LD_PRELOAD 2>/dev/null
systemctl stop ac50.service
sleep 2
"$M/bootmenu" 6 &
P=$!
( sleep 25; kill "$P" 2>/dev/null ) &
W=$!
wait "$P"; R=$?
kill "$W" 2>/dev/null
rm -f "$TRY"                                         # the menu worked
if [ "$R" = 10 ]; then
  exec sh "$M/mpc-console.sh"
fi
systemctl start ac50.service
