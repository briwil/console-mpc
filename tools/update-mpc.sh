#!/bin/sh
# Updates Console on the MPC from your Mac, in one command (the MPC itself has no internet):
#   sh update-mpc.sh                 Console's code (from briwil/console-move) + the bridge (from briwil/console-mpc)
#   sh update-mpc.sh --libs          also the synths / drum machines (the "libs-latest" release of console-move)
#   sh update-mpc.sh --python        also Python + numpy (the "runtime-latest" release of console-mpc)
#   sh update-mpc.sh --all           everything
# It needs: the MPC's root SSH running (USB cable, the SD card's autorun) and a GitHub access key that can READ
# briwil/console-move (a fine-grained token with "Contents: read-only"): put it in the file ~/.console-github-token
# or in the environment variable GITHUB_TOKEN. Quit Console on the MPC first (Shift + STOP).
# Songs and settings (/data/UserData/console/data) are never touched.
set -eu
KEY=${MPC_CLIENT_KEY:-$HOME/.ssh/mpc_sample_client_ed25519}
HOST=root@192.168.155.1
CM=briwil/console-move
CP=briwil/console-mpc
TOKEN=${GITHUB_TOKEN:-$(cat "$HOME/.console-github-token" 2>/dev/null || true)}
DEST=/data/UserData
LIBS=0; PY=0; DRY=0
for a in "$@"; do
  case "$a" in
    --libs) LIBS=1 ;; --python) PY=1 ;; --all) LIBS=1; PY=1 ;; --dry-run) DRY=1 ;;
    *) echo "Unknown option: $a"; exit 2 ;;
  esac
done
say() { printf '%s\n' "$*"; }
mpc() { ssh -p 2222 -i "$KEY" "$HOST" "$@"; }

[ -n "$TOKEN" ] || { say "No GitHub key found. Put it in ~/.console-github-token (see the top of this script)."; exit 1; }
[ "$DRY" = 1 ] && say "(dry run: showing what would happen)"

say "1/5  Is the MPC reachable, and is Console closed?"
if [ "$DRY" = 0 ]; then
  mpc true || { say "Can't reach the MPC. Is the cable in, the SD card in, and the MPC fully started?"; exit 1; }
  if [ "$(mpc "ps | grep -c '[m]ove/app.py'")" != 0 ]; then
    say "Console is running on the MPC. Quit it first (Shift + STOP), then run this again."; exit 1
  fi
fi

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/src" "$T/pack/console/tools/sim"
AUTH="Authorization: Bearer $TOKEN"

say "2/5  Console's code from $CM"
curl -fsSL -H "$AUTH" -H "Accept: application/vnd.github+json" "https://api.github.com/repos/$CM/tarball/main" -o "$T/src.tgz"
tar xzf "$T/src.tgz" -C "$T/src" --strip-components=1
cp -R "$T/src/pi-app" "$T/src/move" "$T/pack/console/"
cp -R "$T/src/tools/sim/stubs" "$T/pack/console/tools/sim/"
rm -rf "$T/pack/console/move/manual" "$T/pack/console/move/anim"

say "3/5  The MPC bridge from $CP"
curl -fsSL "https://github.com/$CP/releases/download/bridge-latest/mpc-bridge.tgz" -o "$T/bridge.tgz"

if [ "$LIBS" = 1 ]; then
  say "     The synths and drum machines (about 75 MB)"
  REL=$(curl -fsSL -H "$AUTH" -H "Accept: application/vnd.github+json" "https://api.github.com/repos/$CM/releases/tags/libs-latest")
  ASSET=$(printf '%s' "$REL" | grep -o '"url": *"[^"]*/assets/[0-9]*"' | head -n 1 | sed 's/.*"\(http[^"]*\)"/\1/')
  [ -n "$ASSET" ] || { say "No libs-latest release found on $CM (run its 'Build Move libraries' action)."; exit 1; }
  LOC=$(curl -fsS -H "$AUTH" -H "Accept: application/octet-stream" -o /dev/null -w '%{redirect_url}' "$ASSET")
  curl -fsSL "$LOC" -o "$T/libs.tgz"
fi
if [ "$PY" = 1 ]; then
  say "     Python + numpy"
  curl -fsSL "https://github.com/$CP/releases/download/runtime-latest/mpc-python.tgz" -o "$T/python.tgz"
fi

say "4/5  Copying to the MPC"
if [ "$DRY" = 1 ]; then
  say "     would copy: console code ($(du -sh "$T/pack" | cut -f1)), bridge, libs=$LIBS, python=$PY"; exit 0
fi
mpc "mkdir -p $DEST/console/mpc $DEST/console/pi-app"
COPYFILE_DISABLE=1 tar --format ustar -cf - -C "$T/pack" console | mpc "cd $DEST && tar xf -"
cat "$T/bridge.tgz" | mpc "cd $DEST/console && tar xzf -"
[ "$LIBS" = 1 ] && cat "$T/libs.tgz" | mpc "cd $DEST/console/pi-app && tar xzf -"
[ "$PY" = 1 ] && cat "$T/python.tgz" | mpc "cd $DEST/console && rm -rf python && tar xzf -"
mpc "sync"
say "5/5  Done. Start Console from the startup menu (PAD 1), or:  sh $DEST/console/mpc/mpc-console.sh"
