#!/bin/sh
# Builds the SD card zip: the folders "autorun" and "Console" to unzip onto the root of the card.
# usage: tools/make-card.sh <console-move checkout> <libs.tgz> <bridge.tgz> <python.tgz> <out folder> [version]
#   libs.tgz    the synths / drum machines   ("libs-latest" release of briwil/console-move)
#   bridge.tgz  the MPC bridge + launcher     ("bridge-latest" release of briwil/console-mpc: mpc-bridge.tgz)
#   python.tgz  Python + numpy for the MPC    ("runtime-latest" release of briwil/console-mpc: mpc-python.tgz)
# Writes <out>/card/{autorun,Console}, and <out>/Console-MPC.zip.  The version defaults to "<bridge BUILD> | move <sha>".
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
CM=$1; LIBS=$2; BRIDGE=$3; PY=$4; OUT=$5; VER=${6:-}
# the firmware's fixed string that autorun.check is made with (the same one launcher/install-boot.sh uses)
SECRET=f7bed1c9-7e90-4731-9194-c996666b4331
OUT=$(mkdir -p "$OUT" && cd "$OUT" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CARD=$OUT/card
rm -rf "$CARD" "$OUT/Console-MPC.zip"
mkdir -p "$CARD/autorun" "$CARD/Console/payload" "$T/console/tools/sim"

cp -R "$CM/pi-app" "$CM/move" "$T/console/"
[ -d "$CM/tools/sim/stubs" ] && cp -R "$CM/tools/sim/stubs" "$T/console/tools/sim/"
tar xzf "$LIBS" -C "$T/console/pi-app"
rm -rf "$T/console/move/manual" "$T/console/move/anim"
tar xzf "$BRIDGE" -C "$T/console"                       # -> console/mpc/ (bridge, launcher scripts, native screens)
[ -f "$T/console/mpc/boot.sh" ] || { echo "the bridge archive has no mpc/boot.sh"; exit 1; }
find "$T" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$T" -name '._*' -delete 2>/dev/null || true
if [ -z "$VER" ]; then
  SHA=$(git -C "$CM" rev-parse --short HEAD 2>/dev/null || echo "?")
  CSHA=$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo "?")
  VER="v$(cat "$HERE/VERSION" 2>/dev/null || echo 0) | $(cat "$T/console/mpc/BUILD" 2>/dev/null || date -u +%F) | move $SHA | card $CSHA"        # (changes with every card build: the Sample installs it)
fi
COPYFILE_DISABLE=1 tar czf "$CARD/Console/payload/console.tgz" -C "$T" console
cp "$PY" "$CARD/Console/payload/python.tgz"
sha256sum "$PY" | cut -c1-16 > "$CARD/Console/payload/PYTHON_VERSION"
( cd "$CARD/Console/payload" && sha256sum console.tgz python.tgz > SHA256SUMS )
printf '%s\n' "$VER" > "$CARD/Console/VERSION"
cp "$HERE/card/Console/install.sh" "$HERE/card/Console/README.txt" "$CARD/Console/"
[ -f "$HERE/launcher/install-screens.raw" ] && cp "$HERE/launcher/install-screens.raw" "$CARD/Console/"   # the progress pictures (tools/make-install-screens.py)
mkdir -p "$CARD/Console/licenses"                      # the licences travel with the files (GPL v3 + the third-party notices)
cp "$HERE/LICENSE" "$CARD/Console/licenses/LICENSE-console-mpc.txt"
[ -f "$CM/LICENSE" ] && cp "$CM/LICENSE" "$CARD/Console/licenses/LICENSE-console.txt"
[ -f "$CM/THIRD-PARTY-NOTICES.md" ] && cp "$CM/THIRD-PARTY-NOTICES.md" "$CARD/Console/licenses/THIRD-PARTY-NOTICES.md"
find "$T/console/pi-app" \( -name 'LICENSE*' -o -name 'COPYING*' -o -name 'NOTICE*' \) -type f 2>/dev/null | head -n 100 | while read -r f; do
  n=$(echo "${f#"$T"/console/pi-app/}" | tr '/' '_'); cp "$f" "$CARD/Console/licenses/$n" 2>/dev/null || true
done
cp "$HERE/card/autorun/"* "$CARD/autorun/"
chmod +x "$CARD/Console/install.sh" "$CARD/autorun/"*.sh
{ cat "$CARD/autorun/autorun.json" "$CARD/autorun/autorun.sh"; printf '%s' "$SECRET"; } | sha256sum | cut -d' ' -f1 | tr -d '\n' > "$CARD/autorun/autorun.check"
( cd "$CARD" && zip -qr -X "$OUT/Console-MPC.zip" autorun Console )
echo "version: $VER"
ls -l "$OUT/Console-MPC.zip"
