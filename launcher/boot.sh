#!/bin/sh
# Runs at power-on (started by the hook in the SD card's autorun.sh, see install-boot.sh): starts Console (no menu). It cannot lock you out of the stock app:
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
[ -x "$C/python/bin/python3" ] || exit 0
if [ -e "$TRY" ]; then rm -f "$TRY"; exit 0; fi      # last time it never got through: let the stock app start

n=0
while ! systemctl is-active --quiet ac50.service && [ $n -lt 90 ]; do sleep 1; n=$((n + 1)); done
# Let the stock app finish starting AND finish talking to the pad/button panel (serial port 3): stopping it half way left the panel
# silent on some boots (Console ran, nothing responded). Wait until the panel's received-byte count has stood still for 4 s
# (at least 12 s, at most 45 s after the stock app is up).
panel_rx() { grep -h '^3:' /proc/tty/driver/* 2>/dev/null | sed -n 's/.* rx:\([0-9]*\).*/\1/p'; }
w=0; last=-1; still=0
while [ $w -lt 45 ]; do
  r=$(panel_rx)
  if [ "$r" = "$last" ]; then still=$((still + 1)); else still=0; last=$r; fi
  [ $w -ge 12 ] && [ $still -ge 4 ] && break
  sleep 1; w=$((w + 1))
done
echo "waited ${w}s for the panel (received bytes: ${last:-?})"
touch "$TRY"                                         # from here on: if Console never gets through, the next power-on starts the stock app
systemctl unset-environment LD_PRELOAD 2>/dev/null
systemctl stop ac50.service
sleep 1
( sleep 40; rm -f "$TRY" ) &                         # Console has been running for a while: the next power-on may try again
exec sh "$M/mpc-console.sh"                          # no menu; when Console ends, the stock MPC app starts again
