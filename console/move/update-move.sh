#!/bin/bash
# The update in one go, run on your Mac:  bash ~/update-move.sh
# (builds on the Pi, copies through the Mac, unpacks on the Move). Once the Move can update itself
# (move-update.py), this is only needed if that doesn't work.
set -e
PI="${PI:-pi@console.local}"
MOVE="${MOVE:-ableton@move.local}"
echo "1/3  Building on the Pi..."
ssh -t "$PI" "cd ~/console-move && git pull -q && bash move/build-for-move.sh update"
echo "2/3  Copying to the Move..."
scp -q "$PI:move-update.tgz" /tmp/move-update.tgz
scp -O -q /tmp/move-update.tgz "$MOVE:/data/UserData/"
echo "3/3  Unpacking on the Move..."
ssh "$MOVE" "cd /data/UserData && python3 -c \"import tarfile; tarfile.open('move-update.tgz').extractall('.')\" && cp -r console-move/pi-app console-move/move console/ && find console/pi-app -name '*.so' -exec touch {} \\;"
echo "Done."
