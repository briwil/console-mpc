#!/bin/sh
# Packs Console (from a checkout of briwil/console-move) + its built libraries + the MPC bridge into one tarball
# that unpacks to console/ (to be copied to /data/UserData/ on the MPC).
# usage: tools/package-app.sh <console-move checkout> <move-libs.tgz> <out.tgz>
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
CM=$1; LIBS=$2; OUT=$3
T=$(mktemp -d)
mkdir -p "$T/console/tools/sim" "$T/console/mpc"
cp -r "$CM/pi-app" "$CM/move" "$T/console/"
cp -r "$CM/tools/sim/stubs" "$T/console/tools/sim/"
tar xzf "$LIBS" -C "$T/console/pi-app"
rm -rf "$T/console/move/manual" "$T/console/move/anim"
cp "$HERE/bridge/libjack_mpc.so" "$HERE/bridge/bridge_demo" "$HERE/bridge/bootmenu" "$HERE/launcher/"*.sh "$HERE/launcher/bootanim.bin" "$T/console/mpc/"
chmod +x "$T/console/mpc/"*
tar czf "$OUT" -C "$T" console
rm -rf "$T"
ls -l "$OUT"
