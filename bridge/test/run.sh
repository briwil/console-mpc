#!/bin/sh
# Host test for the bridge: builds it with fake hardware, plus Console's real core, and runs shim_test.
# usage: bridge/test/run.sh [path-to-console-move-checkout]   (default ../console-move)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
CM=${1:-$HERE/../../../console-move}
OUT=${TMPDIR:-/tmp}/console-mpc-hosttest
mkdir -p "$OUT"
gcc -O1 -g -fPIC -shared -DHOST_TEST -DSEQ_BUTTON_ON -DKNOB_STEP=1 -DNO_RETRIG -fvisibility=hidden -Wno-unused-variable "$HERE/../jackshim.c" -o "$OUT/libjack_mpc_host.so" -lpthread
gcc -O1 -g -fPIC -shared -DHOST_TEST -DSEQ_BUTTON_ON -DKNOB_STEP=1 -fvisibility=hidden -Wno-unused-variable "$HERE/../jackshim.c" -o "$OUT/libjack_mpc_retrig.so" -lpthread
gcc -O1 -fPIC -shared "$CM/pi-app/core/core.c" -o "$OUT/libconsolecore_host.so" -lm -ldl -lpthread
gcc -O1 -g "$HERE/shim_test.c" -o "$OUT/shim_test" -ldl
gcc -O1 -g -DRETRIG_TEST "$HERE/shim_test.c" -o "$OUT/retrig_test" -ldl
"$OUT/shim_test" "$OUT/libjack_mpc_host.so" "$OUT/libconsolecore_host.so"
"$OUT/retrig_test" "$OUT/libjack_mpc_retrig.so" "$OUT/libconsolecore_host.so"
