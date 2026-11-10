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
