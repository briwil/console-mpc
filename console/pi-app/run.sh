#!/bin/bash
# Start Console on the Pi's screen.
# - With the desktop running (for example when you run this over SSH), it opens full screen on the desktop.
# - Without a desktop (boot-to-app), it draws straight to the screen.
cd "$(dirname "$0")"
RUNDIR=/run/user/$(id -u)
if [ -S "$RUNDIR/wayland-0" ]; then
  export XDG_RUNTIME_DIR="$RUNDIR" WAYLAND_DISPLAY=wayland-0 DISPLAY=:0
  export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-wayland,x11}"
else
  export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-kmsdrm}"
fi

# The copy that starts at boot has the screen: pause it while this one runs, and start it again afterwards.
RESTART=0
if systemctl is-active --quiet console 2>/dev/null; then
  echo "Stopping the copy of Console that started at boot (it may ask for your password)..."
  sudo systemctl stop console && RESTART=1
fi
# exit code 75: a software update was installed, so start the new version
while true; do
  python3 console.py "$@" && break
  [ $? = 75 ] || break
done
if [ "$RESTART" = 1 ]; then
  echo "Starting the boot copy of Console again..."
  sudo systemctl start console
fi
