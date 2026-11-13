#!/bin/bash
# Build Console's sound engines (drum synth, effects, drum machines, Schwung synths) for the Ableton Move.
# Run on the Raspberry Pi 5 (same kind of processor as the Move):
#
#     bash ~/console-move/move/build-for-move.sh          (everything: the first time, 15-30 minutes)
#     bash ~/console-move/move/build-for-move.sh update   (after a git pull: the effects and the sound core, and
#                                                          the app's Python files, a minute: ~/move-update.tgz)
#
# The Move's system libraries are older (glibc 2.35) than the Pi's, so a library built normally on the Pi
# won't load there. This builds inside an Ubuntu 22.04 container instead, which has exactly glibc 2.35,
# and leaves everything in ~/move-libs.tgz, ready to copy to the Move.
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$HOME/move-libs.tgz"

if [ "$1" = "update" ]; then
  command -v docker >/dev/null || { echo "Run it without 'update' first."; exit 1; }
  echo "Building the effects and the sound core for the Move..."
  sudo docker run --rm ${DOCKER_PLATFORM:+--platform $DOCKER_PLATFORM} -v "$REPO":/src:ro -v "$HOME":/out ubuntu:22.04 bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq gcc libc6-dev >/dev/null
    gcc -O2 -mtune=cortex-a72 -shared -fPIC -o /out/libconsolefx.so /src/pi-app/fx/fx.c -lm
    gcc -O2 -mtune=cortex-a72 -shared -fPIC -o /out/libconsolecore.so /src/pi-app/core/core.c -ldl -lm
    chown '"$(id -u):$(id -g)"' /out/libconsolefx.so /out/libconsolecore.so'
  rm -rf "$HOME/move-update" && mkdir -p "$HOME/move-update/console-move"
  (cd "$REPO" && tar cf - --exclude='pi-app/splash' --exclude='pi-app/fonts' --exclude='*.so' --exclude='__pycache__' \
      --exclude='pi-app/drums/lxr' --exclude='pi-app/schwung/src' --exclude='pi-app/schwung/modules' pi-app move) \
      | tar xf - -C "$HOME/move-update/console-move"
  mkdir -p "$HOME/move-update/console-move/pi-app/fx" "$HOME/move-update/console-move/pi-app/core"
  mv "$HOME/libconsolefx.so" "$HOME/move-update/console-move/pi-app/fx/"
  mv "$HOME/libconsolecore.so" "$HOME/move-update/console-move/pi-app/core/"
  tar czf "$HOME/move-update.tgz" -C "$HOME/move-update" console-move
  echo "Done: $HOME/move-update.tgz"
  exit 0
fi

if ! command -v docker >/dev/null && [ -z "$CI" ]; then
  echo "Installing Docker (one time)..."
  sudo apt update && sudo apt install -y docker.io
fi

echo "Building in Ubuntu 22.04 (first run downloads it and the compilers: a few minutes)..."
sudo docker run --rm ${DOCKER_PLATFORM:+--platform $DOCKER_PLATFORM} -v "$REPO":/src:ro -v "$HOME":/out ubuntu:22.04 bash -c '
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq gcc g++ make cmake git python3 ca-certificates binutils >/dev/null
  # tune every C/C++ build for the Move'"'"'s processor (Cortex-A72; tuning only, so it runs on any 64-bit ARM),
  # and give the LXR drum synth faster maths (same sound, tested)
  for c in gcc g++; do printf "#!/bin/sh\nexec /usr/bin/%s -mtune=cortex-a72 \"\$@\"\n" $c > /usr/local/bin/$c; chmod +x /usr/local/bin/$c; done
  export DRUMS_CFLAGS="-O3 -ffast-math -fno-finite-math-only"
  cp -r /src/pi-app /build && cd /build
  find . -name "*.so" -delete
  rm -rf schwung/modules schwung/src
  echo "- effects";        gcc -O2 -shared -fPIC -o fx/libconsolefx.so fx/fx.c -lm
  echo "- sound core";     gcc -O2 -shared -fPIC -o core/libconsolecore.so core/core.c -ldl -lm
  echo "- LXR drum synth"; bash drums/build.sh
  cp drums/libdrums.so drums/libdrums_live.so 2>/dev/null || true
  echo "- 606 / 808";      for m in 606 808; do g++ -O2 -shared -fPIC -w -o drums/schwung/lib$m.so drums/schwung/glue$m.cpp; done
  echo "- Sampler";       gcc -O2 -shared -fPIC -o drums/sampler/libsampler.so drums/sampler/sampler.c -lm
  echo "- Ableton Link";   mkdir -p link && git clone -q --depth 1 --branch Link-3.1.3 --recursive https://github.com/Ableton/link.git /tmp/ablink && g++ -std=c++14 -O2 -shared -fPIC -w -DLINK_PLATFORM_UNIX=1 -DLINK_PLATFORM_LINUX=1 -I/tmp/ablink/include -I/tmp/ablink/modules/asio-standalone/asio/include -I/tmp/ablink/extensions/abl_link/include /tmp/ablink/extensions/abl_link/src/abl_link.cpp -o link/liblink.so -lpthread || echo "(Link failed to build)"
  echo "- Machinedrum";    g++ -O2 -std=c++11 -shared -fPIC -w -Idrums/md/vendor -Idrums/md -o drums/md/libmd.so drums/md/glue_md.cpp
  echo "- Schwung synths and drum machines (the longest part)"
  python3 schwung/build.py || echo "(some modules failed: see above)"
  echo
  echo "Newest system library versions needed (the Move has GLIBC 2.35):"
  for f in $(find . -name "*.so"); do objdump -T "$f" | grep -o "GLIBC_2\.[0-9]*\|GLIBCXX_3\.4\.[0-9]*"; done | sort -V | uniq | grep GLIBC_ | tail -n 1
  for f in $(find . -name "*.so"); do objdump -T "$f" | grep -o "GLIBCXX_3\.4\.[0-9]*"; done | sort -V | uniq | tail -n 1
  tar czf /out/move-libs.tgz $(find . -name "*.so") schwung/modules
  chown '"$(id -u):$(id -g)"' /out/move-libs.tgz
'
echo
echo "Done: $OUT"
