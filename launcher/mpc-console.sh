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
# where the sampler and the sample browser look for sounds: the SD card, then the internal drive (leave out any that isn't there)
. "$C/mpc/sdroot.sh" 2>/dev/null
SDR=$(sd_root 2>/dev/null)             # the SD card, whatever its label (/media/sample, /media/SAMPLE ...)
SMP=""
for d in "$SDR" /data/UserData/UserLibrary/Samples /data/UserData/console/samples; do [ -n "$d" ] && [ -d "$d" ] && SMP="$SMP${SMP:+:}$d"; done
export CONSOLE_SAMPLES="$SMP"
mkdir -p "$C/data"
# Projects, presets and settings (CONSOLE_DATA) live on the SD card: <card>/Console/data, made if it isn't there. The first time,
# what is on the internal drive is copied across (the internal copy stays where it is). No card, or it can't be written: the internal drive.
DATA="$C/data"
if [ -n "$SDR" ] && [ -d "$SDR" ]; then
  SD="$SDR/Console"
  if [ ! -d "$SD/data" ]; then
    mkdir -p "$SD" && rm -rf "$SD/data.new" && cp -r "$C/data" "$SD/data.new" && mv "$SD/data.new" "$SD/data" && sync
    [ -f "$C/knob-sensitivity" ] && cp "$C/knob-sensitivity" "$SD/knob-sensitivity" 2>/dev/null
  fi
  if [ -d "$SD/data" ] && touch "$SD/data/.writable" 2>/dev/null; then rm -f "$SD/data/.writable"; DATA="$SD/data"; fi
fi
export CONSOLE_DATA="$DATA"
echo "$DATA" > "$C/data-folder.txt"

restore() { systemctl start ac50.service; }
trap 'touch "$C/STOP"' INT TERM

systemctl unset-environment LD_PRELOAD 2>/dev/null
systemctl stop ac50.service
sleep 1
rm -f "$C/STOP"
rm -f "$C/app.pid"        # a leftover note from an earlier run makes Console think another copy is running
while :; do
  rm -f /tmp/console-native.rgb /tmp/console-pagemode
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
rm -f "$C/STOP" /tmp/console-native.rgb /tmp/console-pagemode
restore
echo "Console ended (exit code $CODE). The stock MPC app is starting again. Log: $C/app.log"
