#!/bin/sh
# Starts Console on the Akai MPC Sample. Run it from the root SSH shell:  sh /data/UserData/console/mpc/mpc-console.sh
# It stops the stock MPC app (frees the screen, audio and control surface), runs Console, and starts the stock
# app again when Console ends (Shift + STOP in Console = save and quit; or Ctrl-C here).
C=/data/UserData/console
export HOME=/data/UserData
export TMPDIR=/tmp
export CONSOLE_LIBJACK="$C/mpc/libjack_mpc.so"
export CONSOLE_PLATFORM=move
export PYTHONUNBUFFERED=1
mkdir -p "$C/data"

restore() { systemctl start ac50.service; }
trap 'touch "$C/STOP"' INT TERM

systemctl unset-environment LD_PRELOAD 2>/dev/null
systemctl stop ac50.service
sleep 1
rm -f "$C/STOP"
rm -f "$C/app.pid"        # a leftover note from an earlier run makes Console think another copy is running
while :; do
  rm -f /tmp/console-native.rgb
  if [ -f "$C/mpc/mpc_app.py" ]; then APP="$C/mpc/mpc_app.py"; else APP="$C/move/app.py"; fi      # mpc_app.py = Console with its native 320x240 screens
  "$C/python/bin/python3" "$APP" > "$C/app.log" 2>&1 &
  PID=$!
  while [ ! -f "$C/STOP" ] && kill -0 "$PID" 2>/dev/null; do sleep 1; done
  if [ -f "$C/STOP" ]; then          # asked to stop: let it save, then quit
    kill "$PID" 2>/dev/null
    for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
    kill -9 "$PID" 2>/dev/null
  fi
  wait "$PID"; CODE=$?
  [ "$CODE" = 75 ] && [ ! -f "$C/STOP" ] || break      # 75 = the app wants a restart
done
rm -f "$C/STOP" /tmp/console-native.rgb
restore
echo "Console ended (exit code $CODE). The stock MPC app is starting again. Log: $C/app.log"
