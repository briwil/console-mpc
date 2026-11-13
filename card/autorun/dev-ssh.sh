#!/bin/sh
# Developers only: starts a key-only SSH server on the USB cable (192.168.155.1, port 2222). It runs only if the files
# authorized_keys and ssh_host_ed25519_key are in the card's ConsoleDev folder (best: updating doesn't touch it) or in the
# autorun folder (Console doesn't need it).
set -eu
umask 077
D=${1:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
RAM=/run/console-ssh
UNIT=console-usb-ssh
[ -x /usr/sbin/sshd ] || exit 1
grep -q ' /run tmpfs ' /proc/mounts || exit 1
mkdir -p "$RAM" /run/sshd
chmod 700 "$RAM"; chmod 755 /run/sshd
systemctl is-active --quiet "$UNIT.service" && exit 0
cp "$D/authorized_keys" "$RAM/authorized_keys"
cp "$D/ssh_host_ed25519_key" "$RAM/ssh_host_ed25519_key"
chmod 600 "$RAM/authorized_keys" "$RAM/ssh_host_ed25519_key"
cat > "$RAM/sshd_config" <<CONF
Port 2222
ListenAddress 192.168.155.1
HostKey $RAM/ssh_host_ed25519_key
PidFile $RAM/sshd.pid
AuthorizedKeysFile $RAM/authorized_keys
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers root
AllowTcpForwarding no
X11Forwarding no
CONF
cat > "$RAM/worker.sh" <<'WORKER'
#!/bin/sh
RAM=/run/console-ssh
n=0
while ! grep -q '192.168.155.1' /proc/net/fib_trie 2>/dev/null; do
  [ "$n" -ge 60 ] && exit 1
  sleep 1; n=$((n + 1))
done
exec /usr/sbin/sshd -D -e -f "$RAM/sshd_config"
WORKER
chmod 700 "$RAM/worker.sh"
systemd-run --unit="$UNIT" --collect --no-block --property=After=ac50.service /bin/sh "$RAM/worker.sh" >/dev/null 2>&1
