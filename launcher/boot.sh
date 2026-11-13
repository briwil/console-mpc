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
. "$M/sdroot.sh" 2>/dev/null
SDR=$(sd_root 2>/dev/null)
[ -n "$SDR" ] && [ -e "$SDR/NOCONSOLE" ] && exit 0
[ -e "$C/NOBOOT" ] && exit 0
[ -x "$C/python/bin/python3" ] || exit 0
if [ -e "$TRY" ]; then rm -f "$TRY"; exit 0; fi      # last time it never got through: let the stock app start

takeover() {
  echo "panel before: $(grep "^ *3:" /proc/tty/driver/* | sed "s/.*tx/tx/")"
  echo "taking over at uptime $(cut -d. -f1 /proc/uptime) s (firmware tool seen: ${seen:-0}, waited ${w:-0}s)"
  touch "$TRY"                                         # from here on: if Console never gets through, the next power-on starts the stock app
  systemctl unset-environment LD_PRELOAD 2>/dev/null
  systemctl stop ac50.service
  sleep 2
}

if [ -z "${CONSOLE_TOOK_OVER:-}" ]; then
  n=0
  while ! systemctl is-active --quiet ac50.service && [ $n -lt 90 ]; do sleep 1; n=$((n + 1)); done
  # The stock launcher first runs az0x-firmware-tool (it talks to the pad / button panel over the serial port), then starts the app.
  # Stopping the service while that tool is still running left the panel half started: Console ran and nothing responded. So wait for
  # the tool to finish (or the app to be up), then take over at once: no need to wait for the stock app to load. (The panel's start-up
  # handshake the stock app does after that is now done by the bridge itself.)
  w=0; seen=0
  while [ $w -lt 90 ]; do
    if ps | grep -q '[a]z0x-firmware-too[l]'; then seen=1
    elif [ $seen = 1 ] || ps | grep -q '[M]PC Sampl[e]'; then break
    fi
    sleep 1; w=$((w + 1))
  done
  sleep 1
  # The panel's serial MIDI port only works once the stock start-up has talked to the panel (its counter, tx, climbs to ~1300) and
  # the MIDI device exists. Taking over a few seconds too early gave a menu that could not open the port: pads dead, MPC after 15 s
  # (the log said "midi: could not open"). So wait for both, for up to 40 s, then go on regardless.
  n=0; tx=0
  while [ $n -lt 40 ]; do
    tx=$(grep "^ *3:" /proc/tty/driver/* 2>/dev/null | sed 's/.*tx:\([0-9]*\).*/\1/' | head -n1)
    [ -e /dev/snd/midiC0D0 ] && [ "${tx:-0}" -gt 100 ] 2>/dev/null && break
    sleep 1; n=$((n + 1))
  done
  echo "panel ready after ${n}s (tx ${tx:-?}, midi device: $([ -e /dev/snd/midiC0D0 ] && echo yes || echo no))"
  UP_MIN=0
  [ -f "$C/UP_MIN" ] && UP_MIN=$(cat "$C/UP_MIN")                  # (optional extra wait, in seconds of uptime:  echo 40 > $C/UP_MIN)
  up=$(cut -d. -f1 /proc/uptime)
  [ "$up" -lt "$UP_MIN" ] && sleep $((UP_MIN - up))
  takeover
else
  echo "the stock app was already stopped by install.sh"
  touch "$TRY"
fi
# The panel is sometimes left silent when the stock app is stopped in the middle of its own start-up (about one boot in three if we
# take over at 7-10 s). The menu notices (nothing from the panel for 5 s: exit 12); then the stock app gets the screen back, settles
# for 20 s, and we try again (up to 3 tries; the last one waits for the normal 15 s and then leaves it to the stock app).
attempt=1
while :; do
  SILENT=5
  [ "$attempt" -ge 3 ] && SILENT=0
  [ -n "${CONSOLE_TOOK_OVER:-}" ] && SILENT=0
  "$M/bootmenu" 15 "$M/bootanim.bin" "$SILENT" &                       # the startup menu: PAD 1 = Console, PAD 2 = MPC; no answer = MPC
  P=$!
  ( sleep 40; kill "$P" 2>/dev/null ) &
  W=$!
  wait "$P"; R=$?
  kill "$W" 2>/dev/null
  rm -f "$TRY"                                         # the menu worked
  if [ "$R" = 12 ] && [ "$attempt" -lt 3 ]; then
    echo "panel silent on try $attempt: giving the stock app back for a while, then trying again"
    systemctl start ac50.service
    attempt=$((attempt + 1))
    sleep 20
    takeover
    continue
  fi
  break
done
if [ "$R" = 10 ]; then
  exec sh "$M/mpc-console.sh"
fi
systemctl start ac50.service
