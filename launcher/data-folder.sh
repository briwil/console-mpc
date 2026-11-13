# Where Console keeps your projects, presets and settings (CONSOLE_DATA), and the backup of them on the Sample's internal drive.
# Sourced by mpc-console.sh.   resolve_data <sd card root or empty> <console dir>   sets DATA and BK;   backup_data   refreshes BK.
#
#   <card>/ConsoleData    a folder of its own on the card. The zip holds only "autorun" and "Console", so replacing those two
#                         (the way to update) never touches it.
#   <console dir>/data-backup   a copy on the internal drive, refreshed at every start (when it is small enough), so a card
#                         that lost its ConsoleData (wiped, replaced, another card) is filled again from it.
# The first time ConsoleData is made, it is filled from the first of: the old place on the card (Console/data, version 1.0.0),
# the backup, the internal drive's own data. No card, or it can't be written to: the internal drive (<console dir>/data).

resolve_data() {
  _sdr=$1; _c=$2
  BK="$_c/data-backup"
  DATA="$_c/data"
  mkdir -p "$DATA"
  [ -n "$_sdr" ] && [ -d "$_sdr" ] || return 0
  _sd="$_sdr/ConsoleData"
  if [ ! -d "$_sd" ]; then
    for _src in "$_sdr/Console/data" "$BK" "$_c/data"; do
      if [ -d "$_src" ]; then
        rm -rf "$_sd.new" && cp -r "$_src" "$_sd.new" && mv "$_sd.new" "$_sd" && sync
        echo "data: ConsoleData made from $_src"
        break
      fi
    done
    [ -d "$_sd" ] || mkdir -p "$_sd"
  fi
  if [ -d "$_sd" ] && touch "$_sd/.writable" 2>/dev/null; then rm -f "$_sd/.writable"; DATA="$_sd"; fi
}

backup_data() {
  [ "$DATA" = "$_c/data" ] && return 0                           # (the data is on the internal drive already)
  _kb=$(du -sk "$DATA" 2>/dev/null | cut -f1)
  [ -n "$_kb" ] || return 0
  if [ "$_kb" -gt "${BACKUP_MAX_KB:-400000}" ]; then echo "data backup skipped: $((_kb / 1024)) MB is more than the internal drive should hold"; return 0; fi
  _free=$(df -Pk "$_c" 2>/dev/null | awk 'NR==2{print $4}')
  if [ "${_free:-0}" -lt $((_kb * 2 + 200000)) ]; then echo "data backup skipped: not enough room on the internal drive"; return 0; fi
  rm -rf "$BK.new" && cp -r "$DATA" "$BK.new" && rm -rf "$BK" && mv "$BK.new" "$BK" && echo "data backup done ($((_kb / 1024)) MB)"
}
