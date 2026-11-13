#!/bin/sh
# Host test of the card installer with fake inputs:  sh card/test/run.sh
set -u
HERE=$(cd "$(dirname "$0")/../.." && pwd)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fail=0
ok() { echo "ok:   $*"; }
bad() { echo "FAIL: $*"; fail=1; }

# fake inputs
mkdir -p "$W/cm/pi-app" "$W/cm/move" "$W/cm/tools/sim/stubs" "$W/libs/mods/synth" "$W/bridge/mpc" "$W/py/python/bin"
echo code > "$W/cm/pi-app/app.py"; echo m > "$W/cm/move/app.py"; echo synth > "$W/libs/mods/synth/s.so"
printf '#!/bin/sh\necho BOOT "$0" >> "${BOOTLOG:-/dev/null}"\n' > "$W/bridge/mpc/boot.sh"
echo "abc1234 2026-11-13 00:00" > "$W/bridge/mpc/BUILD"
printf '#!/bin/sh\necho py\n' > "$W/py/python/bin/python3"; chmod +x "$W/py/python/bin/python3" "$W/bridge/mpc/boot.sh"
( cd "$W/libs" && tar czf "$W/libs.tgz" mods ); ( cd "$W/bridge" && tar czf "$W/bridge.tgz" mpc ); ( cd "$W/py" && tar czf "$W/py.tgz" python )
git -C "$W/cm" init -q 2>/dev/null; 

sh "$HERE/tools/make-card.sh" "$W/cm" "$W/libs.tgz" "$W/bridge.tgz" "$W/py.tgz" "$W/out" "v1" >/dev/null || { bad "make-card"; exit 1; }
CARD=$W/out/card
[ -f "$W/out/Console-MPC.zip" ] && ok "zip built" || bad "zip"
# autorun.check = sha256(json + sh + secret)
exp=$({ cat "$CARD/autorun/autorun.json" "$CARD/autorun/autorun.sh"; printf '%s' f7bed1c9-7e90-4731-9194-c996666b4331; } | sha256sum | cut -d' ' -f1 | tr -d '\n')
[ "$(cat "$CARD/autorun/autorun.check")" = "$exp" ] && [ "$(wc -c < "$CARD/autorun/autorun.check")" = 64 ] && ok "autorun.check" || bad "autorun.check"
( cd "$W" && rm -rf unz && mkdir unz && unzip -q out/Console-MPC.zip -d unz ) && [ -f "$W/unz/Console/install.sh" ] && [ -f "$W/unz/autorun/autorun.sh" ] && ok "zip layout" || bad "zip layout"

run() {  # run install.sh on card $1 with fresh "power-on" (/run cleared)
  rm -rf "$W/run"; mkdir -p "$W/run"
  CONSOLE_DATA_ROOT="$W/data" CONSOLE_RUN="$W/run" BOOTLOG="$W/boot.log" sh "$1/Console/install.sh"
}
mkdir -p "$W/data"
: > "$W/boot.log"
run "$CARD"
[ "$(cat "$W/data/console/installed.version")" = v1 ] && [ -f "$W/data/console/pi-app/app.py" ] && [ -f "$W/data/console/python/bin/python3" ] && [ -f "$W/data/console/pi-app/mods/synth/s.so" ] && ok "first install" || bad "first install"
grep -q BOOT "$W/boot.log" && ok "starts Console after installing" || bad "boot not started"

# user data survives, same version: no reinstall
echo song > "$W/data/console/data.keep"; mkdir -p "$W/data/console/data"; echo song > "$W/data/console/data/s1"
echo MARK > "$W/data/console/pi-app/marker"
: > "$W/boot.log"; run "$CARD"
[ -f "$W/data/console/pi-app/marker" ] && grep -q BOOT "$W/boot.log" && ok "same version: no reinstall, still starts" || bad "same version"

# run twice in one power-on: second does nothing
: > "$W/boot.log"; CONSOLE_DATA_ROOT="$W/data" CONSOLE_RUN="$W/run" BOOTLOG="$W/boot.log" sh "$CARD/Console/install.sh"
[ ! -s "$W/boot.log" ] && ok "once per power-on" || bad "lock"

# update
sh "$HERE/tools/make-card.sh" "$W/cm" "$W/libs.tgz" "$W/bridge.tgz" "$W/py.tgz" "$W/out2" "v2" >/dev/null
echo newer > "$W/cm/pi-app/app.py"; sh "$HERE/tools/make-card.sh" "$W/cm" "$W/libs.tgz" "$W/bridge.tgz" "$W/py.tgz" "$W/out2" "v2" >/dev/null
echo pyold > "$W/data/console/python/KEEP"
run "$W/out2/card"
[ "$(cat "$W/data/console/installed.version")" = v2 ] && [ "$(cat "$W/data/console/pi-app/app.py")" = newer ] && [ ! -f "$W/data/console/pi-app/marker" ] && ok "update replaces the code" || bad "update"
[ -f "$W/data/console/data/s1" ] && ok "songs/data kept" || bad "data lost"
[ -f "$W/data/console/python/KEEP" ] && ok "python not unpacked again (same runtime)" || bad "python re-unpacked"

# damaged payload: nothing changes, old Console still starts
mkdir -p "$W/bad" && cp -R "$W/out2/card/." "$W/bad/" && echo v3 > "$W/bad/Console/VERSION" && echo junk >> "$W/bad/Console/payload/console.tgz"
: > "$W/boot.log"; run "$W/bad"
[ "$(cat "$W/data/console/installed.version")" = v2 ] && grep -q BOOT "$W/boot.log" && grep -q DAMAGED "$W/bad/Console/install-status.txt" && ok "damaged files: refused, old Console starts" || bad "damaged"

# not enough room
: > "$W/boot.log"; echo v4 > "$W/bad/Console/VERSION"; cp "$W/out2/card/Console/payload/console.tgz" "$W/bad/Console/payload/console.tgz"
rm -rf "$W/run"; mkdir -p "$W/run"; CONSOLE_FREE_KB=1000 CONSOLE_DATA_ROOT="$W/data" CONSOLE_RUN="$W/run" BOOTLOG="$W/boot.log" sh "$W/bad/Console/install.sh"
grep -q "NOT ENOUGH ROOM" "$W/bad/Console/install-status.txt" && [ "$(cat "$W/data/console/installed.version")" = v2 ] && ok "no room: refused" || bad "no room"

# NOCONSOLE
: > "$W/boot.log"; touch "$W/out2/card/NOCONSOLE"; run "$W/out2/card"
[ ! -s "$W/boot.log" ] && ok "NOCONSOLE: nothing started" || bad "NOCONSOLE"; rm -f "$W/out2/card/NOCONSOLE"

# UNINSTALL keeps data
touch "$W/out2/card/Console/UNINSTALL"; run "$W/out2/card"
[ ! -d "$W/data/console/pi-app" ] && [ ! -d "$W/data/console/python" ] && [ -f "$W/data/console/data/s1" ] && ok "UNINSTALL removes Console, keeps data" || bad "UNINSTALL"
rm -f "$W/out2/card/Console/UNINSTALL"; : > "$W/boot.log"; run "$W/out2/card"
[ "$(cat "$W/data/console/installed.version")" = v2 ] && grep -q BOOT "$W/boot.log" && ok "installs again after UNINSTALL is deleted" || bad "reinstall"

[ "$fail" = 0 ] && echo "ALL PASSED" || { echo "SOME FAILED"; exit 1; }
