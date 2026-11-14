#!/bin/sh
# Updates Console on the MPC from your Mac, in one command (the MPC itself has no internet):
#   sh update-mpc.sh                 Console's code + the bridge (both from briwil/console-mpc)
#   sh update-mpc.sh --libs          also the synths / drum machines (the "libs-latest" release of console-mpc)
#   sh update-mpc.sh --python        also Python + numpy (the "runtime-latest" release of console-mpc)
#   sh update-mpc.sh --all           everything
# It needs: the MPC's root SSH running (USB cable, the SD card's autorun). The repo is public, so no key is needed
#   --no-start: don't start Console again at the end
# (a GitHub key in ~/.console-github-token or GITHUB_TOKEN is used if you have one).
# Songs and settings (/data/UserData/console/data) are never touched.
set -eu
KEY=${MPC_CLIENT_KEY:-$HOME/.ssh/mpc_sample_client_ed25519}
HOST=root@192.168.155.1
CM=briwil/console-mpc
CP=briwil/console-mpc
TOKEN=${GITHUB_TOKEN:-$(cat "$HOME/.console-github-token" 2>/dev/null || true)}
DEST=/data/UserData
LIBS=0; PY=0; DRY=0
for a in "$@"; do
  case "$a" in
    --libs) LIBS=1 ;; --python) PY=1 ;; --all) LIBS=1; PY=1 ;; --dry-run) DRY=1 ;; --no-start) NOSTART=1 ;;
    *) echo "Unknown option: $a"; exit 2 ;;
  esac
done
say() { printf '%s\n' "$*"; }
mpc() { ssh -p 2222 -i "$KEY" "$HOST" "$@"; }

[ "$DRY" = 1 ] && say "(dry run: showing what would happen)"

say "1/5  Is the MPC reachable, and is Console closed?"
if [ "$DRY" = 0 ]; then
  mpc true || { say "Can't reach the MPC. Is the cable in, the SD card in, and the MPC fully started?"; exit 1; }
  if [ "$(mpc "ps | grep -c '[a]pp.py'")" != 0 ]; then
    say "Console is running on the MPC. Quit it first (Shift + STOP), then run this again."; exit 1
  fi
fi

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/src" "$T/pack/console/tools/sim"
if [ -n "$TOKEN" ]; then AUTH="Authorization: Bearer $TOKEN"; else AUTH="X-No-Key: 1"; fi

say "2/5  Console's code from $CM"
curl -fsSL -H "$AUTH" -H "Accept: application/vnd.github+json" "https://api.github.com/repos/$CM/tarball/main" -o "$T/src.tgz"
tar xzf "$T/src.tgz" -C "$T/src" --strip-components=1
cp -R "$T/src/console/pi-app" "$T/src/console/move" "$T/pack/console/"
cp -R "$T/src/console/tools/sim/stubs" "$T/pack/console/tools/sim/"
rm -rf "$T/pack/console/move/manual" "$T/pack/console/move/anim"
find "$T/pack/console" -name "*.so" -delete          # (the repo holds PC builds of the libraries; the MPC keeps its own, from the libs release)

say "3/5  The MPC bridge from $CP"
curl -fsSL "https://github.com/$CP/releases/download/bridge-latest/mpc-bridge.tgz" -o "$T/bridge.tgz"

if [ "$LIBS" = 1 ]; then
  say "     The synths and drum machines (about 75 MB)"
  curl -fsSL "https://github.com/$CP/releases/download/libs-latest/move-libs.tgz" -o "$T/libs.tgz"
fi
if [ "$PY" = 1 ]; then
  say "     Python + numpy"
  curl -fsSL "https://github.com/$CP/releases/download/runtime-latest/mpc-python.tgz" -o "$T/python.tgz"
fi

say "4/5  Copying to the MPC"
if [ "$DRY" = 1 ]; then
  say "     would copy: console code ($(du -sh "$T/pack" | cut -f1)), bridge, libs=$LIBS, python=$PY"; exit 0
fi
mpc "if pgrep -f \"[m]pc-console.sh\" >/dev/null 2>&1; then touch $DEST/console/STOP; i=0; while pgrep -f \"[m]pc-console.sh\" >/dev/null 2>&1 && [ \$i -lt 25 ]; do sleep 1; i=\$((i+1)); done; fi; true"   # (Console is stopped while its files change)
mpc "mkdir -p $DEST/console/mpc $DEST/console/pi-app"
COPYFILE_DISABLE=1 tar --format ustar -cf - -C "$T/pack" console | mpc "cd $DEST && tar xf -"
[ "$LIBS" = 1 ] && cat "$T/libs.tgz" | mpc "cd $DEST/console/pi-app && tar xzf -"
cat "$T/bridge.tgz" | mpc "cd $DEST/console && tar xzf -"
mpc "[ -f $DEST/console/mpc/libconsolecore.so ] && cp $DEST/console/mpc/libconsolecore.so $DEST/console/pi-app/core/libconsolecore.so && cp $DEST/console/mpc/libschwunghost.so $DEST/console/pi-app/schwung/libschwunghost.so || true"     # (our sound core and module host)
mpc "[ -f $DEST/console/mpc/vst2fx.so ] && cp $DEST/console/mpc/vst2fx.so $DEST/console/pi-app/schwung/modules/stompbox/vst2fx.so && cp $DEST/console/mpc/vst2fx.so $DEST/console/pi-app/schwung/modules/guitar/dsp.so && mkdir -p $DEST/console/pi-app/schwung/modules/model72 && cp $DEST/console/mpc/vst2fx.so $DEST/console/pi-app/schwung/modules/model72/dsp.so && for m in $DEST/console/pi-app/schwung/modules/op1-* $DEST/console/pi-app/schwung/modules/vhs-vibes $DEST/console/pi-app/schwung/modules/profit5 $DEST/console/pi-app/schwung/modules/jn106 $DEST/console/pi-app/schwung/modules/sturm $DEST/console/pi-app/schwung/modules/boris $DEST/console/pi-app/schwung/modules/monomodule $DEST/console/pi-app/schwung/modules/clementine $DEST/console/pi-app/schwung/modules/w9 $DEST/console/pi-app/schwung/modules/oxzygen; do if grep -q audio_fx \$m/module.json; then cp $DEST/console/mpc/vst2fx.so \$m/vst2fx.so; else cp $DEST/console/mpc/vst2fx.so \$m/dsp.so; fi; done || true"     # (the VST2 effect host for STOMPBOX)
[ "$PY" = 1 ] && cat "$T/python.tgz" | mpc "cd $DEST/console && rm -rf python && tar xzf -"
mpc "sync"
if [ "${NOSTART:-0}" = 1 ]; then
  say "5/5  Done. Start Console from the startup menu (PAD 1)."
else
  mpc "rm -f $DEST/console/STOP; nohup sh $DEST/console/mpc/mpc-console.sh >/dev/null 2>&1 </dev/null &"
  say "5/5  Done. Console is starting on the MPC."
fi
