#!/bin/sh
# Builds libjack_mpc.so for the MPC Sample (aarch64 glibc) with no ARM headers or libraries
# (same technique as test/build.sh: hand-declared functions + stand-in libraries to link against).
set -e
cd "$(dirname "$0")"
CF="-O2 -fPIC -fno-stack-protector -ffreestanding -fvisibility=hidden -Wall -Wextra -Wno-unused-function -Wno-unused-parameter"
clang --target=aarch64-linux-gnu $CF -c jackshim.c -o jackshim.o
llvm-nm -u jackshim.o | awk '{print $2}' | sort -u > undef.txt
grep '^snd_' undef.txt > undef_alsa.txt || true
grep -v '^snd_' undef.txt > undef_libc.txt
mkdir -p stubs
for pair in "libc.so.6:undef_libc.txt" "libasound.so.2:undef_alsa.txt"; do
  lib=${pair%%:*}; list=${pair##*:}
  : > stubs/$lib.c
  while read -r sym; do echo "void $sym(void) {}" >> stubs/$lib.c; done < $list
  clang --target=aarch64-linux-gnu -shared -nostdlib -fPIC -fuse-ld=lld -Wl,-soname=$lib -o stubs/$lib stubs/$lib.c
done
ld.lld -shared -o libjack_mpc.so jackshim.o -L stubs -l:libc.so.6 -l:libasound.so.2 \
  --no-as-needed -z noexecstack --build-id=none -soname libjack_mpc.so
llvm-strip libjack_mpc.so
echo built: $(ls -l libjack_mpc.so | awk '{print $5}') bytes

# ---- the demo program (bridge_demo): needs only libc ----
clang --target=aarch64-linux-gnu -O2 -fno-pic -fno-stack-protector -ffreestanding -Wall -Wextra -Wno-unused-parameter -c demo.c -o demo.o
llvm-nm -u demo.o | awk '{print $2}' | sort -u > undef_demo.txt
: > stubs/demo_libc.c
while read -r sym; do echo "void $sym(void) {}" >> stubs/demo_libc.c; done < undef_demo.txt
mkdir -p stubs/demo
clang --target=aarch64-linux-gnu -shared -nostdlib -fPIC -fuse-ld=lld -Wl,-soname=libc.so.6 -o stubs/demo/libc.so.6 stubs/demo_libc.c 2>/dev/null
ld.lld -o bridge_demo demo.o -L stubs/demo -l:libc.so.6 --dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  --no-as-needed -z noexecstack --build-id=none
llvm-strip bridge_demo
echo built: bridge_demo $(ls -l bridge_demo | awk '{print $5}') bytes
