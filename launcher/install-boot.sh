#!/bin/sh
# Adds Console's startup menu to the SD card's autorun (run on the MPC, as root, with the SD card in):
#   sh /data/UserData/console/mpc/install-boot.sh            install
#   sh /data/UserData/console/mpc/install-boot.sh remove     put the original autorun back
# It adds ONE hook to autorun/autorun.sh (after its "D=" line) and recomputes autorun/autorun.check
# (SHA-256 of autorun.json + autorun.sh + the firmware's fixed string). The originals are saved in
# /data/UserData/console/autorun-backup/.   AUTORUN_DIR=... overrides the folder (for testing).
set -eu
A=${AUTORUN_DIR:-/media/sample/autorun}
B=${BACKUP_DIR:-/data/UserData/console/autorun-backup}
SECRET=f7bed1c9-7e90-4731-9194-c996666b4331

check() { { cat "$A/autorun.json" "$A/autorun.sh"; printf '%s' "$SECRET"; } | sha256sum | cut -d' ' -f1 | tr -d '\n'; }

[ -f "$A/autorun.sh" ] && [ -f "$A/autorun.json" ] && [ -f "$A/autorun.check" ] || { echo "No autorun folder at $A (is the SD card in?)"; exit 1; }

if [ "${1:-}" = remove ]; then
  [ -f "$B/autorun.sh" ] || { echo "No backup in $B"; exit 1; }
  cp "$B/autorun.sh" "$A/autorun.sh"; cp "$B/autorun.check" "$A/autorun.check"; sync
  echo "Original autorun restored."; exit 0
fi

if grep -q console-boot "$A/autorun.sh"; then echo "Already installed."; exit 0; fi
[ "$(check)" = "$(cat "$A/autorun.check")" ] || { echo "autorun.check does not match the files now: not touching it."; exit 1; }
mkdir -p "$B"
[ -f "$B/autorun.sh" ] || { cp "$A/autorun.sh" "$B/autorun.sh"; cp "$A/autorun.check" "$B/autorun.check"; }

N=$(grep -n '^D=' "$A/autorun.sh" | head -n 1 | cut -d: -f1)
[ -n "$N" ] || { echo "Can't find the D= line in autorun.sh: not touching it."; exit 1; }
T=$(mktemp)
head -n "$N" "$A/autorun.sh" > "$T"
cat >> "$T" <<'HOOK'
# console-boot: start Console's startup menu (installed by install-boot.sh; harmless if Console isn't there)
if [ -x /data/UserData/console/mpc/boot.sh ] && command -v systemd-run >/dev/null 2>&1; then
  systemd-run --unit=console-boot --collect --no-block --property=After=ac50.service \
    /bin/sh /data/UserData/console/mpc/boot.sh >/dev/null 2>&1 || true
fi
HOOK
tail -n +"$((N + 1))" "$A/autorun.sh" >> "$T"
cp "$T" "$A/autorun.sh"; rm -f "$T"
check > "$A/autorun.check"
sync
echo "Installed. Restart the MPC: you get the startup menu (PAD 1 = Console, PAD 2 = MPC; no answer = MPC)."
echo "Undo:  sh $0 remove     Skip it once:  put a file called NOCONSOLE on the SD card."
