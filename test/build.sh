#!/bin/sh
# Builds mpc_test for the MPC Sample (aarch64 glibc) with no ARM headers or libraries:
# the program's libc / libasound functions are declared by hand, and tiny stand-in
# libraries with the right names are linked against so the real ones are used on the device.
set -e
cd "$(dirname "$0")"
CF="-O2 -fno-pic -fno-stack-protector -ffreestanding -Wall -Wextra -Wno-unused-parameter"
clang --target=aarch64-linux-gnu $CF -c mpc_test.c -o mpc_test.o
llvm-nm -u mpc_test.o | awk '{print $2}' | sort -u > undef.txt
grep '^snd_' undef.txt > undef_alsa.txt || true
grep -v '^snd_' undef.txt > undef_libc.txt
mkdir -p stubs
for pair in "libc.so.6:undef_libc.txt" "libasound.so.2:undef_alsa.txt"; do
  lib=${pair%%:*}; list=${pair##*:}
  : > stubs/$lib.c
  while read -r sym; do echo "void $sym(void) {}" >> stubs/$lib.c; done < $list
  clang --target=aarch64-linux-gnu -shared -nostdlib -fPIC -fuse-ld=lld -Wl,-soname=$lib -o stubs/$lib stubs/$lib.c
done
ld.lld -o mpc_test mpc_test.o -L stubs -l:libc.so.6 -l:libasound.so.2 \
  --dynamic-linker=/lib/ld-linux-aarch64.so.1 --no-as-needed -z noexecstack --build-id=none
llvm-strip mpc_test
echo built: $(ls -l mpc_test | awk '{print $5}') bytes
