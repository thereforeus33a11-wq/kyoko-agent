#!/usr/bin/env bash
# Copy each kept checkpoint to the volume as soon as it is written, one file at a time, so a pod stop loses no
# training. Usage: keep_copy.sh <keep dir on /w> <dir on /workspace> <pid of the training run>
# A file counts as written when its size and mtime have held for 30 s. It is copied as <name>.part under the
# volume lock (/w/locks/volume: one big volume read or write at a time, as bison_setup.sh and the watchdog do),
# read back and compared by sha256, then renamed; <name>.sha256 is written beside it (podio.py down reads it).
# It runs until the training pid has gone, then does one last pass. One line per copy in its log.
set -uo pipefail
SRC=$1; DST=$2; PID=${3:-}
VLOCK=/w/locks/volume
mkdir -p "$DST" "$(dirname $VLOCK)"
log() { echo "$(date -u +%FT%TZ) $*"; }
pass() {
  for f in $(ls -tr "$SRC"/keep-epoch=*.ckpt 2> /dev/null); do
    b=$(basename "$f")
    [ -s "$DST/$b" ] && [ -s "$DST/$b.sha256" ] && continue
    s1=$(stat -c %s.%Y "$f"); sleep 30; s2=$(stat -c %s.%Y "$f")
    [ "$s1" = "$s2" ] || continue
    want=$(sha256sum "$f" | cut -d' ' -f1)
    t0=$(date +%s)
    ( flock 9
      cp "$f" "$DST/$b.part" && got=$(sha256sum "$DST/$b.part" | cut -d' ' -f1) && [ "$got" = "$want" ] \
        && mv -f "$DST/$b.part" "$DST/$b" && echo "$want" > "$DST/$b.sha256"
    ) 9> $VLOCK
    if [ -s "$DST/$b.sha256" ]; then
      echo "$want" > "$f.sha256"
      log "copied $b ($(stat -c %s "$f") bytes, sha256 $want) in $(( $(date +%s) - t0 )) s"
    else
      rm -f "$DST/$b.part"; log "COPY FAILED for $b: will try again"
    fi
  done
}
log "watching $SRC -> $DST (training pid ${PID:-none})"
while [ -n "$PID" ] && kill -0 "$PID" 2> /dev/null; do pass; sleep 60; done
pass
log "KEEP-COPY-DONE"
