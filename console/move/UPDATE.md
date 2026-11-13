# Updating the Move (what to run, and where)

1. **Pi:**  `cd ~/console-move && git pull && bash move/build-for-move.sh update`   -> ~/move-update.tgz
2. **Mac:** `scp pi@console.local:move-update.tgz ~/Downloads/`
3. **Mac:** `scp -O ~/Downloads/move-update.tgz ableton@move.local:/data/UserData/`
4. **Move (ssh ableton@move.local):**
   `cd /data/UserData && python3 -c "import tarfile; tarfile.open('move-update.tgz').extractall('.')" && cp -r console-move/pi-app console-move/move console/ && find console/pi-app -name '*.so' -exec touch {} \;`

`cp -r` only adds and overwrites files; the built libraries in `console/pi-app` stay (apart from the effects library and the sound core, which are replaced).
The `touch` marks the libraries newer than their source files, so the app doesn't try to rebuild them (the Move has no compiler).
