#!/bin/sh
# Host test of vst2fx.so (the VST2 effect host for Console's insert effects), with a fake VST2 plugin.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$HERE/../../console/pi-app/schwung/vst2fx/vst2fx.c
OUT=${TMPDIR:-/tmp}/vst2fx-test
rm -rf "$OUT"; mkdir -p "$OUT/plugins"
gcc -O1 -g -fPIC -shared -fvisibility=hidden -Wall -Wextra -Wno-unused-parameter "$SRC" -o "$OUT/vst2fx.so" -ldl
gcc -O1 -g -fPIC -shared "$HERE/fakevst.c" -o "$OUT/plugins/fakevst.so"
gcc -O1 -g "$HERE/vst2fx_test.c" -o "$OUT/vst2fx_test" -ldl
"$OUT/vst2fx_test" "$OUT/vst2fx.so" "$OUT/plugins" "$OUT/module"
# the GUITAR instrument: the module host (schwung/host.c) feeds the audio input to vst2fx.so
HOST=$HERE/../../console/pi-app/schwung/host.c
gcc -O1 -g -fPIC -shared -I"$HERE/../../console/pi-app/schwung" "$HOST" -o "$OUT/libschwunghost.so" -ldl -lpthread
gcc -O1 -g "$HERE/guitar_test.c" -o "$OUT/guitar_test" -ldl
"$OUT/guitar_test" "$OUT/libschwunghost.so" "$OUT/plugins" "$OUT/module2" "$OUT"
