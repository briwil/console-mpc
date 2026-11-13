# Finds the SD card, whatever it is called (the mount point is named after the card's label: /media/sample, /media/SAMPLE,
# /media/MPCSD ...). Used by sourcing:   . "$(dirname "$0")/sdroot.sh"; SD=$(sd_root)
# sd_root prints the mount point, or nothing if there's no card. SD_ROOT=/some/folder overrides it (tests);
# CONSOLE_MOUNTS=/some/file reads that instead of /proc/mounts (tests).
sd_root() {
  if [ -n "${SD_ROOT:-}" ]; then printf '%s\n' "$SD_ROOT"; return 0; fi
  _f=${CONSOLE_MOUNTS:-/proc/mounts}
  _r=$(sed -n 's#^/dev/mmcblk1p[0-9]* \(/[^ ]*\) .*#\1#p' "$_f" 2>/dev/null | head -n 1)
  [ -n "$_r" ] || _r=$(sed -n 's#^/dev/[^ ]* \(/media/[^ ]*\) .*#\1#p' "$_f" 2>/dev/null | head -n 1)
  [ -n "$_r" ] && printf '%s\n' "$_r" | sed 's/\\040/ /g'
  return 0
}
