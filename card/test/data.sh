#!/bin/sh
# Test of launcher/data-folder.sh: where the projects live, and that replacing the Console / autorun folders can't lose them.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
T=$(mktemp -d); fails=0
ok()   { echo "ok:   $1"; }
fail() { echo "FAIL: $1"; fails=$((fails + 1)); }
check() { if eval "$1"; then ok "$2"; else fail "$2"; fi; }
. "$HERE/../../launcher/data-folder.sh"

C=$T/internal/console; mkdir -p "$C/data"; echo old-internal > "$C/data/p.txt"

# 1. version 1.0.0 card: the projects are in Console/data -> copied to ConsoleData
CARD=$T/card1; mkdir -p "$CARD/Console/data"; echo mine > "$CARD/Console/data/p.txt"
resolve_data "$CARD" "$C" >/dev/null
check '[ "$DATA" = "$CARD/ConsoleData" ] && [ "$(cat "$CARD/ConsoleData/p.txt")" = mine ]' "1.0.0 card: Console/data is copied to ConsoleData"

# 2. update by dragging: the Console folder is replaced (its data folder goes), ConsoleData stays
rm -rf "$CARD/Console"; mkdir -p "$CARD/Console"
resolve_data "$CARD" "$C" >/dev/null
check '[ "$(cat "$CARD/ConsoleData/p.txt")" = mine ]' "replacing the Console folder keeps the projects"

# 3. a backup is made, and fills a card that lost ConsoleData
backup_data >/dev/null
check '[ "$(cat "$C/data-backup/p.txt")" = mine ]' "the projects are copied to the internal drive"
echo newer > "$CARD/ConsoleData/q.txt"; backup_data >/dev/null
rm -rf "$CARD/ConsoleData"
resolve_data "$CARD" "$C" >/dev/null
check '[ "$(cat "$CARD/ConsoleData/p.txt")" = mine ] && [ "$(cat "$CARD/ConsoleData/q.txt")" = newer ]' "a card that lost ConsoleData is filled from the backup"

# 4. a new card with nothing: the internal original (no backup yet)
rm -rf "$C/data-backup"; CARD2=$T/card2; mkdir -p "$CARD2"
resolve_data "$CARD2" "$C" >/dev/null
check '[ "$(cat "$CARD2/ConsoleData/p.txt")" = old-internal ]' "an empty card gets the internal drive's data"

# 5. no card: the internal drive, and no backup of itself
resolve_data "" "$C" >/dev/null
check '[ "$DATA" = "$C/data" ] && backup_data >/dev/null && [ ! -d "$C/data-backup" ]' "no card: the internal drive is used"

# 6. too big: the backup is skipped, the data stays
resolve_data "$CARD" "$C" >/dev/null
BACKUP_MAX_KB=1 backup_data >/dev/null
check '[ ! -d "$C/data-backup" ] && [ "$(cat "$CARD/ConsoleData/p.txt")" = mine ]' "data over the size limit is not copied"

rm -rf "$T"
[ "$fails" = 0 ] && echo "ALL PASSED" || { echo "$fails FAILED"; exit 1; }
