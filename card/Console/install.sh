#!/bin/sh
# Console for the MPC Sample: installs or updates Console from this card onto the Sample's internal drive, then starts it.
# (The card can't run programs itself: it is mounted "noexec". So the programs are copied once, here; your projects and
# presets stay on the card, in Console/data.)  Started by autorun/autorun.sh at power-on.
#
#   first start / a newer card version : copies Console (about a minute); the stock MPC screen stays up meanwhile
#   same version already installed     : goes straight to Console's startup menu
#   a file  NOCONSOLE  next to this Console folder : does nothing (the stock MPC app starts)
#   a file  Console/UNINSTALL          : removes Console from the Sample (your songs on the card stay); delete the file to install again
#   what happened: Console/install-status.txt (here) and console/install.log (on the Sample)
SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)        # <card>/Console
ROOT=$(dirname -- "$SRC")                                # the card
DATA_ROOT=${CONSOLE_DATA_ROOT:-/data/UserData}           # (tests change these three)
RUN=${CONSOLE_RUN:-/run}
C=$DATA_ROOT/console
P=$SRC/payload
mkdir -p "$C" || exit 1
exec >> "$C/install.log" 2>&1
echo "--- install.sh $(date)"
mkdir "$RUN/console-install.lock" 2>/dev/null || { echo "already ran at this power-on"; exit 0; }

say() { echo "$*"; printf '%s\n' "$*" > "$SRC/install-status.txt" 2>/dev/null; }
start() { [ -x "$C/mpc/boot.sh" ] && exec /bin/sh "$C/mpc/boot.sh"; exit 0; }      # (boot.sh has its own safety checks)

[ -e "$ROOT/NOCONSOLE" ] && { echo "NOCONSOLE is on the card: leaving the stock app alone"; exit 0; }

if [ -e "$SRC/UNINSTALL" ]; then
  for f in "$C"/* "$C"/.[!.]*; do
    [ -e "$f" ] || continue
    case "$f" in "$C/data"|"$C/install.log") ;; *) rm -rf "$f" ;; esac
  done
  say "Console was removed from the Sample ($(date)). Delete Console/UNINSTALL (and Console/payload) to install it again."
  exit 0
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

echo "installing: $NEW (was: ${OLD:-nothing})"
kb() { _k=$(du -k "$1" 2>/dev/null | cut -f1); echo "${_k:-0}"; }
NEED=$(( 2 * ($(kb "$P/console.tgz") + $(kb "$P/python.tgz")) + 150000 ))
FREE=${CONSOLE_FREE_KB:-$(df -kP "$DATA_ROOT" | tail -n 1 | awk '{print $4}')}
if [ "${FREE:-0}" -lt "$NEED" ]; then
  say "NOT ENOUGH ROOM on the Sample: needs $((NEED / 1024)) MB free, has $((FREE / 1024)) MB. Console was not installed."
  start
fi

if [ -f "$P/SHA256SUMS" ]; then
  if ! ( cd "$P" && sha256sum -c SHA256SUMS ) >/dev/null 2>&1; then
    say "THE FILES ON THE CARD ARE DAMAGED (checksum). Copy the Console folder to the card again. Console was not changed."
    start
  fi
fi

rm -f "$C/installed.version"                          # (an install that is cut short is started again at the next power-on)
T=$DATA_ROOT/.console-install
rm -rf "$T"; mkdir -p "$T"
if ! tar xzf "$P/console.tgz" -C "$T" || [ ! -d "$T/console/mpc" ]; then
  rm -rf "$T"; say "COULDN'T UNPACK Console/payload/console.tgz. Console was not installed."; exit 1
fi
for d in pi-app move tools mpc; do
  [ -d "$T/console/$d" ] || continue
  rm -rf "$C/$d"; mv "$T/console/$d" "$C/$d"
done
rm -rf "$T"

PYNEW=$(cat "$P/PYTHON_VERSION" 2>/dev/null)
if [ -f "$P/python.tgz" ] && { [ "$PYNEW" != "$(cat "$C/python.version" 2>/dev/null)" ] || [ ! -x "$C/python/bin/python3" ]; }; then
  rm -rf "$C/python"
  if ! tar xzf "$P/python.tgz" -C "$C" || [ ! -x "$C/python/bin/python3" ]; then
    say "COULDN'T UNPACK Console/payload/python.tgz. Console was not installed."; exit 1
  fi
  printf '%s\n' "$PYNEW" > "$C/python.version"
fi
chmod +x "$C"/mpc/*.sh "$C/mpc/bootmenu" 2>/dev/null
sync
printf '%s\n' "$NEW" > "$C/installed.version"
sync
say "Console installed: $NEW ($(date))"
start
