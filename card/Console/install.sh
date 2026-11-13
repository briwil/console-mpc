#!/bin/sh
# Console for the MPC Sample: installs or updates Console from this card onto the Sample's internal drive, then starts it.
# (The card can't run programs itself: it is mounted "noexec". So the programs are copied once, here; your projects and
# presets stay on the card, in Console/data.)  Started by autorun/autorun.sh at power-on.
#
#   first start / a newer card version : the screen says INSTALLING CONSOLE, Console is copied (about a minute), then it starts
#   same version already installed     : goes straight to Console's startup menu
#   a file  NOCONSOLE  next to this Console folder : does nothing (the stock MPC app starts)
#   a file  Console/UNINSTALL          : removes Console from the Sample (your songs on the card stay); delete the file to install again
#   what happened: Console/install-status.txt (here) and console/install.log (on the Sample)
SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)        # <card>/Console
ROOT=$(dirname -- "$SRC")                                # the card
DATA_ROOT=${CONSOLE_DATA_ROOT:-/data/UserData}           # (tests change these)
RUN=${CONSOLE_RUN:-/run}
FB=${CONSOLE_FB:-/dev/fb0}
BLANK=${CONSOLE_BLANK:-/sys/class/graphics/fb0/blank}
SLP=${CONSOLE_SLEEP:-1}
C=$DATA_ROOT/console
P=$SRC/payload
ATT=$C/install-attempt
mkdir -p "$C" || exit 1
exec >> "$C/install.log" 2>&1
echo "--- install.sh $(date)"
mkdir "$RUN/console-install.lock" 2>/dev/null || { echo "already ran at this power-on"; exit 0; }

say() { echo "$*"; printf '%s\n' "$*" > "$SRC/install-status.txt" 2>/dev/null; tail -n 150 "$C/install.log" > "$SRC/install-log.txt" 2>/dev/null; }
start() { rm -f "$ATT"; [ -x "$C/mpc/boot.sh" ] && exec /bin/sh "$C/mpc/boot.sh"; exit 0; }      # (boot.sh has its own safety checks)

[ -e "$ROOT/NOCONSOLE" ] && { echo "NOCONSOLE is on the card: leaving the stock app alone"; exit 0; }

if [ -e "$SRC/UNINSTALL" ]; then
  for f in "$C"/* "$C"/.[!.]*; do
    [ -e "$f" ] || continue
    case "$f" in "$C/data"|"$C/install.log") ;; *) rm -rf "$f" ;; esac
  done
  say "Console was removed from the Sample ($(date)). Delete Console/UNINSTALL (and Console/payload) to install it again."
  exit 0
fi

if [ -e "$ATT" ]; then                                   # the last install was cut short (power off?): this time the stock app starts
  rm -f "$ATT"
  say "The last install did not finish. Skipped at this power-on; it is tried again at the next one. ($(date))"
  start
fi

NEW=$(cat "$SRC/VERSION" 2>/dev/null)
OLD=$(cat "$C/installed.version" 2>/dev/null)
if [ -z "$NEW" ] || [ ! -f "$P/console.tgz" ]; then
  echo "nothing to install on this card: starting what is installed ($OLD)"
  start
fi
if [ "$NEW" = "$OLD" ] && [ -x "$C/mpc/boot.sh" ] && [ -x "$C/python/bin/python3" ]; then
  echo "version $OLD is already installed"
  start
fi

# ---- an install is needed: take the screen (stop the stock app the way boot.sh does), show where we are
echo "installing: $NEW (was: ${OLD:-nothing})"
n=0
while ! systemctl is-active --quiet ac50.service && [ $n -lt 90 ]; do sleep "$SLP"; n=$((n + 1)); done
# (the stock launcher's firmware tool sets up the pad / button panel first: stopping the app while it runs leaves the panel half started)
w=0; seen=0
while [ $w -lt 90 ]; do
  if ps | grep -q '[a]z0x-firmware-too[l]'; then seen=1
  elif [ $seen = 1 ] || ps | grep -q '[M]PC Sampl[e]'; then break
  fi
  sleep "$SLP"; w=$((w + 1))
done
sleep "$SLP"
touch "$ATT"
systemctl unset-environment LD_PRELOAD 2>/dev/null
systemctl stop ac50.service
sleep "$SLP"
[ -w "$BLANK" ] && { echo 1 > "$BLANK"; echo 0 > "$BLANK"; }
for f in name bits_per_pixel stride virtual_size blank state; do echo "fb0 $f: $(cat /sys/class/graphics/fb0/$f 2>&1)"; done
# The progress pictures. One background loop keeps the screen open the whole time (the display may clear itself when the last user
# closes it) and draws the current picture once a second (so nothing can wipe it for long). show N = switch to picture N.
FRAMEF=$RUN/console-install.frame
draw() {
  [ -f "$SRC/install-screens.raw" ] || return 0
  dd if="$SRC/install-screens.raw" of="$FB" bs=307200 skip="$(cat "$FRAMEF" 2>/dev/null || echo 0)" count=1 2>"$RUN/console-install.dd"
}
show() {
  echo "$1" > "$FRAMEF"
  draw || echo "drawing picture $1 failed: $(cat "$RUN/console-install.dd" 2>/dev/null)"
}
stop_screen() { rm -f "$FRAMEF"; [ -n "${LOOP:-}" ] && kill "$LOOP" 2>/dev/null; LOOP=; }
echo 0 > "$FRAMEF"
( exec 3<>"$FB"; while [ -f "$FRAMEF" ]; do draw 2>/dev/null; sleep 1; done ) &
LOOP=$!
# nothing has been changed yet: the old Console (if there is one) can still start; else the stock app
fail_safe() { say "$1"; show 5; sleep $((SLP * 6)); stop_screen; rm -f "$ATT"
  if [ -x "$C/mpc/boot.sh" ] && [ -x "$C/python/bin/python3" ]; then export CONSOLE_TOOK_OVER=1; exec /bin/sh "$C/mpc/boot.sh"; fi
  systemctl start ac50.service; exit 1; }
# something was half replaced: back to the stock app
fail_broken() { say "$1"; show 5; sleep $((SLP * 6)); stop_screen; rm -f "$ATT"; systemctl start ac50.service; exit 1; }

show 0
kb() { _k=$(du -k "$1" 2>/dev/null | cut -f1); echo "${_k:-0}"; }
NEED=$(( 2 * ($(kb "$P/console.tgz") + $(kb "$P/python.tgz")) + 150000 ))
FREE=${CONSOLE_FREE_KB:-$(df -kP "$DATA_ROOT" | tail -n 1 | awk '{print $4}')}
if [ "${FREE:-0}" -lt "$NEED" ]; then
  fail_safe "NOT ENOUGH ROOM on the Sample: needs $((NEED / 1024)) MB free, has $((FREE / 1024)) MB. Console was not installed."
fi

show 1
if [ -f "$P/SHA256SUMS" ]; then
  if ! ( cd "$P" && sha256sum -c SHA256SUMS ) >/dev/null 2>&1; then
    fail_safe "THE FILES ON THE CARD ARE DAMAGED (checksum). Copy the Console folder to the card again. Console was not changed."
  fi
fi

show 2
rm -f "$C/installed.version"                          # (an install that is cut short is started again at the next power-on)
T=$DATA_ROOT/.console-install
rm -rf "$T"; mkdir -p "$T"
if ! tar xzf "$P/console.tgz" -C "$T" || [ ! -d "$T/console/mpc" ]; then
  rm -rf "$T"; fail_safe "COULDN'T UNPACK Console/payload/console.tgz. Console was not installed."
fi
for d in pi-app move tools mpc; do
  [ -d "$T/console/$d" ] || continue
  rm -rf "$C/$d"; mv "$T/console/$d" "$C/$d"
done
rm -rf "$T"

PYNEW=$(cat "$P/PYTHON_VERSION" 2>/dev/null)
if [ -f "$P/python.tgz" ] && { [ "$PYNEW" != "$(cat "$C/python.version" 2>/dev/null)" ] || [ ! -x "$C/python/bin/python3" ]; }; then
  show 3
  rm -rf "$C/python"
  if ! tar xzf "$P/python.tgz" -C "$C" || [ ! -x "$C/python/bin/python3" ]; then
    fail_broken "COULDN'T UNPACK Console/payload/python.tgz. Console was not installed."
  fi
  printf '%s\n' "$PYNEW" > "$C/python.version"
fi
chmod +x "$C"/mpc/*.sh "$C/mpc/bootmenu" 2>/dev/null
sync
printf '%s\n' "$NEW" > "$C/installed.version"
sync
say "Console installed: $NEW ($(date))"
show 4
sleep "$SLP"
stop_screen
rm -f "$ATT"
export CONSOLE_TOOK_OVER=1                            # (boot.sh: the stock app is already stopped; go straight to the startup menu)
exec /bin/sh "$C/mpc/boot.sh"
