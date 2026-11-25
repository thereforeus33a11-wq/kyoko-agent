#!/usr/bin/env bash
# Rejudging the five-style voice (styles2): bring back on a fresh container disk what the scoring needs, one big
# volume read at a time under the volume lock (/w/locks/volume). Nothing of hers in this file.
#  - yesterday's notes and scoring archives, unpacked under $S/prev (never over another agent's folder)
#  - the four checked style sets into /w/range_v1 (their archive tars; the sets' stats.json hold the style gates)
#  - faster-whisper large-v3 into /w/models_local
#  - keep-epoch=1749.ckpt into /w/piper-styles-keep (sha256 checked against the volume's .sha256)
# Usage: bash styles2_setup.sh   Settings: S (default /w/range_build/styles2). Ends with STYLES2-SETUP-DONE.
set -uo pipefail
S=${S:-/w/range_build/styles2}; A=/workspace/yume/range_v1_archive; K=/workspace/yume/piper-styles-keep; VLOCK=/w/locks/volume
mkdir -p /w/locks /w/models_local /w/piper-styles-keep $S/prev $S/logs
t() { echo "$(date -u +%T) $*"; }
for f in styles_notes_run2.tgz styles_eval.tgz; do
  ( flock 9; tar xzf $A/$f -C $S/prev ) 9> $VLOCK && t "$f unpacked under $S/prev" || t "FAILED $f"
done
for s in soft whisper loud yell; do
  if [ -s /w/range_v1/$s/ds/stats.json ]; then t "$s there already"; continue; fi
  t0=$(date +%s)
  ( flock 9; tar xf $A/$s.tar -C /w ) 9> $VLOCK || t "FAILED untar $s"
  t "$s: $(find /w/range_v1/$s ! -type d | wc -l) files, $(du -sh /w/range_v1/$s | cut -f1), $(( $(date +%s) - t0 )) s"
done
if [ ! -s /w/models_local/faster-whisper-large-v3/model.bin ]; then
  t0=$(date +%s)
  ( flock 9; cp -r /workspace/models/faster-whisper-large-v3 /w/models_local/ ) 9> $VLOCK || t "FAILED faster-whisper copy"
  t "faster-whisper: $(du -sh /w/models_local/faster-whisper-large-v3 | cut -f1), $(( $(date +%s) - t0 )) s"
fi
b=keep-epoch=1749.ckpt
if [ ! -s /w/piper-styles-keep/$b ]; then
  t0=$(date +%s)
  ( flock 9; cp $K/$b /w/piper-styles-keep/$b.part; cp $K/$b.sha256 /w/piper-styles-keep/$b.sha256.vol ) 9> $VLOCK
  want=$(cut -d' ' -f1 /w/piper-styles-keep/$b.sha256.vol); got=$(sha256sum /w/piper-styles-keep/$b.part | cut -d' ' -f1)
  if [ -n "$want" ] && [ "$want" = "$got" ]; then
    mv -f /w/piper-styles-keep/$b.part /w/piper-styles-keep/$b; echo "$got" > /w/piper-styles-keep/$b.sha256
    rm -f /w/piper-styles-keep/$b.sha256.vol
    t "$b: $(stat -c %s /w/piper-styles-keep/$b) bytes, sha256 $got (= the volume's), $(( $(date +%s) - t0 )) s"
  else
    t "FAILED $b: sha256 $got differs from the volume's '$want'"
  fi
fi
t STYLES2-SETUP-DONE
