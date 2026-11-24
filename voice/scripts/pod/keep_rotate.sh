#!/usr/bin/env bash
# For a volume too small to hold every kept checkpoint: keep the NEWEST kept checkpoint on the volume (a pod stop
# loses no training: the run resumes from it), and a slim copy of EVERY kept checkpoint next to it on /w (the
# generator's inference weights, ~67 MB, for scoring and export; slim_ckpt.py), which the caller fetches elsewhere.
# Usage: keep_rotate.sh <keep dir on /w> <dir on /workspace> <training pid>
# Volume footprint: at most two kept checkpoints of this run at once (the new one is copied before the old one is
# deleted), plus whatever else is in <dir> (left alone). Each copy: <name>.part under the volume lock
# (/w/locks/volume), read back and compared by sha256, renamed, <name>.sha256 beside it. Only files named
# keep-epoch=*.ckpt(.sha256) in <dir> are ever deleted, and only older ones than the verified newest.
# A file counts as written when its size and mtime have held for 30 s. One line per action in the log.
set -uo pipefail
SRC=$1; DST=$2; PID=${3:-}
VLOCK=/w/locks/volume; PY=/w/piper-env/bin/python; J=/w/job/scripts
mkdir -p "$DST" "$SRC/slim" "$(dirname $VLOCK)"
log() { echo "$(date -u +%FT%TZ) $*"; }
epoch_of() { basename "$1" | sed 's/keep-epoch=\([0-9]*\)\.ckpt/\1/'; }
stable() { local s1 s2; s1=$(stat -c %s.%Y "$1"); sleep 30; s2=$(stat -c %s.%Y "$1"); [ "$s1" = "$s2" ]; }
last_fail=0
ERR=$SRC/slim/copy_err.txt
errline() { tr '\n' ' ' < $ERR 2> /dev/null | cut -c1-160; }
# a volume copy counts only with a .sha256 beside it that holds the local file's digest
vok() { [ -s "$1" ] && [ -s "$1.sha256" ] && [ -s "$SRC/$(basename $1).sha256" ] && [ "$(cat "$1.sha256")" = "$(cat "$SRC/$(basename $1).sha256")" ]; }
older() { for v in $(ls "$DST"/keep-epoch=*.ckpt 2> /dev/null | sort -V); do [ "$(epoch_of $v)" -lt "$1" ] && echo "$v"; done; }
drop_older() { for v in $(older "$1"); do rm -f "$v" "$v.sha256"; log "removed older volume copy $(basename $v) (its slim stays)"; done; }
# 0 copied and verified; 1 not copied (nothing left behind); 2 data copied and verified but its .sha256 did not land
copy_one() {
  local f=$1 want=$2 bb; bb=$(basename "$1")
  echo "$want" > "$SRC/slim/$bb.want"   # written by cp, which (unlike a shell redirect) reports a failed close
  ( flock 9
    cp "$f" "$DST/$bb.part" || exit 1
    [ "$(sha256sum "$DST/$bb.part" | cut -d' ' -f1)" = "$want" ] || { echo "read-back sha256 differs"; exit 1; }
    mv -f "$DST/$bb.part" "$DST/$bb" || exit 1
    cp "$SRC/slim/$bb.want" "$DST/$bb.sha256" || exit 2
    [ "$(cat "$DST/$bb.sha256" 2> /dev/null)" = "$want" ] || { echo "the .sha256 did not land"; exit 2; }
  ) 9> $VLOCK > $ERR 2>&1
  local rc=$?
  [ $rc = 1 ] && rm -f "$DST/$bb.part" "$DST/$bb" "$DST/$bb.sha256"
  return $rc
}
pass() {
  # 1. a slim of every kept checkpoint
  for f in $(ls "$SRC"/keep-epoch=*.ckpt 2> /dev/null | sort -V); do
    b=$(basename "$f"); s="$SRC/slim/${b%.ckpt}.gen.pt"
    [ -s "$s.sha256" ] && continue
    stable "$f" || continue
    if $PY $J/slim_ckpt.py "$f" "$s" > "$s.log" 2>&1 && $PY $J/slim_ckpt.py --check "$s" "$f" >> "$s.log" 2>&1; then
      sha256sum "$s" | cut -d' ' -f1 > "$s.sha256"; log "slim $(basename $s) ($(stat -c %s "$s") bytes, sha256 $(cat $s.sha256))"
    else
      log "SLIM FAILED for $b: $(tail -1 $s.log)"; rm -f "$s"
    fi
  done
  # 2. the newest kept checkpoint on the volume
  new=$(ls "$SRC"/keep-epoch=*.ckpt 2> /dev/null | sort -V | tail -1); [ -n "$new" ] || return
  b=$(basename "$new"); E=$(epoch_of "$new")
  vok "$DST/$b" && return
  [ $(( $(date +%s) - last_fail )) -lt 600 ] && return   # after a failed copy, wait 10 min before the next try
  stable "$new" || return
  want=$(sha256sum "$new" | cut -d' ' -f1); t0=$(date +%s)
  # copy first: this run's older copy stays until the new one is verified
  copy_one "$new" "$want"; rc=$?
  if [ $rc = 1 ] && [ -n "$(older "$E")" ]; then
    # no room (the quota): free this run's older copies first, then copy again (the slims, off the pod, and the
    # full checkpoints on /w keep every epoch meanwhile)
    log "no room to copy $b beside the older copy ($(errline)): removing this run's older volume copies first"
    drop_older "$E"; copy_one "$new" "$want"; rc=$?
  fi
  if [ $rc = 2 ]; then   # the data is there and verified, only its .sha256 did not land: free room and write it
    drop_older "$E"; ( flock 9; cp "$SRC/slim/$b.want" "$DST/$b.sha256" ) 9> $VLOCK >> $ERR 2>&1
    [ "$(cat "$DST/$b.sha256" 2> /dev/null)" = "$want" ] && rc=0
  fi
  if [ $rc = 0 ]; then
    echo "$want" > "$new.sha256"
    log "copied $b ($(stat -c %s "$new") bytes, sha256 $want) in $(( $(date +%s) - t0 )) s"
    drop_older "$E"
  else
    last_fail=$(date +%s)
    log "COPY FAILED for $b ($(errline)): the volume keeps $(ls "$DST"/keep-epoch=*.ckpt 2> /dev/null | sort -V | tr '\n' ' ')- next try in 10 min"
  fi
}
log "watching $SRC -> $DST, newest only, slims in $SRC/slim (training pid ${PID:-none})"
while [ -n "$PID" ] && kill -0 "$PID" 2> /dev/null; do pass; sleep 60; done
last_fail=0; pass
log "KEEP-ROTATE-DONE"
