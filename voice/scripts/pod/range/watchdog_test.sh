#!/usr/bin/env bash
# Tests of range/watchdog.sh on the pod: every piece but the real stop. Every watchdog here runs with DRY_RUN=1, its
# own STATE and its own off file, so the real one (/w/watchdog) is not touched and nothing can be stopped.
#  A  scratch folders, a key that cannot work: in use by load (4 CPU burners), by the GPU (a 20 s matmul loop, about
#     0.5 GB), by a file change; off by the off file; then idle -> archives (file count checked), note, dry stop;
#  B  the same state again: the folders are unchanged since their archives, nothing is written again;
#  C  the archive folder cannot be written: no stop at first, the note says so, stop after the grace time;
#  D  the real folders, the real archive folder on the volume and the pod's own key (DRY_RUN): the key check at the
#     start, /w/range_v1 and /w/range_build archived for real, the note in watchdog_dryrun.txt (removed at the end);
#  E  bison_setup.sh's restore of that archive, into a scratch folder: every file back with its sha256, not SETUP_OK,
#     never over a file that is there;
#  F  the stop command is there (its --help), the pod id and key are set. The stop itself is NOT run.
# D needs the GPU, the CPU and /w/logs, /w/range_v1, /w/range_build quiet for a minute (it gives up after 200 s).
# No voice data in this script (D's archive holds what /w/range_build holds; it stays on the pod's volume).
# Run: setsid nohup bash /w/job/scripts/range/watchdog_test.sh > /w/upload/watchdog_test.log 2>&1 < /dev/null &
#      (about 6 minutes; the log NOT under /w/logs, or D never sees a quiet minute). Ends with WDTEST-DONE.
set -uo pipefail
WD=${WD:-/w/watchdog.sh}
T=/w/wdtest; rm -rf $T; mkdir -p $T/watch $T/data/range_v1/sub $T/data/range_build
echo x > $T/data/range_v1/sub/a.txt; echo y > $T/data/range_build/b.txt; ln -s b.txt $T/data/range_build/l
say() { echo "### $(date -u +%T) $*"; }
wd() {  # wd <state> [VAR=value ...]: one dry-run watchdog on the scratch folders, in the background
  local st=$1; shift
  env DRY_RUN=1 RUNPOD_API_KEY=not-a-key STATE=$T/$st WATCH=$T/watch ARCHIVE="$T/data/range_v1 $T/data/range_build" ARCH=$T/arch \
      NOTE=$T/note_$st.txt OFF=$T/NO_WATCHDOG SAMPLE_S=2 CHECK_S=10 LOAD_WIN_S=10 IDLE_S=30 QUIET_MIN=1 "$@" \
      setsid nohup bash $WD > /dev/null 2>&1 < /dev/null &
}
waitend() {  # waitend <state> <seconds>: until that watchdog has exited
  local i
  for i in $(seq 1 $2); do [ -e $T/$1/pid ] || { sleep 1; [ -e $T/$1/pid ] || return 0; }; sleep 1; done
  say "watchdog $1 still runs after $2 s: ending it (pid $(cat $T/$1/pid))"; kill "$(cat $T/$1/pid)"; return 1
}
show() { sed "s/^/    /" $T/$1/watchdog.log | cut -c1-330; }

say "watchdog under test: $WD ($(sha256sum $WD | cut -c1-12)); the real one: pid $(cat /w/watchdog/pid 2>/dev/null || echo none)"
say "A: in use by load, by the GPU, by a file change; off by the file; then idle -> archive, note, dry stop"
wd A; sleep 1
say "A: 4 CPU burners for 20 s"; for i in 1 2 3 4; do timeout 20 sha256sum /dev/zero > /dev/null & done; sleep 24
say "A: GPU burner for 20 s (free $(nvidia-smi --query-gpu=memory.free --format=csv,noheader))"
/w/dfn-env/bin/python -c "
import torch, time
x = torch.randn(8192, 8192, device='cuda'); t = time.time()
while time.time() - t < 20: (x @ x).sum().item()
print('gpu burn done, peak MiB', torch.cuda.max_memory_allocated() // 2**20)" 2>&1 | tail -1
sleep 28
say "A: files quiet by now; off file for 12 s"; touch $T/NO_WATCHDOG; sleep 12; rm -f $T/NO_WATCHDOG
sleep 10
say "A: a file changes under the watched folder"; echo z > $T/watch/f
waitend A 150; say "A: exit, log:"; show A
say "A: note:"; sed "s/^/    /" $T/note_A.txt
say "A: archives:"; ls -la $T/arch | sed "s/^/    /"; for f in $T/arch/*.tar; do tar tvf $f | sed "s/^/      /"; done

say "B: the same state again: nothing changed since the archives were written"
wd A; waitend A 90; say "B: log (new lines):"; show A | sed -n '/watchdog started/h;//!H;${x;p}' | tail -8

say "C: the archive folder cannot be written (ARCH=/proc/wdtest), grace 20 s"
wd C ARCH=/proc/wdtest ARCHIVE_GRACE_S=20; waitend C 120; say "C: log:"; show C; say "C: note:"; sed "s/^/    /" $T/note_C.txt | head -12

say "D: the real folders and the real volume paths, the pod's own key, DRY_RUN"
env DRY_RUN=1 STATE=$T/D OFF=$T/NO_WATCHDOG SAMPLE_S=2 CHECK_S=10 LOAD_WIN_S=10 IDLE_S=30 QUIET_MIN=1 \
    setsid nohup bash $WD > /dev/null 2>&1 < /dev/null &
sleep 2; waitend D 200; say "D: log:"; show D
say "D: note /workspace/yume/logs/watchdog_dryrun.txt:"; sed "s/^/    /" /workspace/yume/logs/watchdog_dryrun.txt
ls -la /workspace/yume/range_v1_archive | sed "s/^/    /"

say "E: restore as bison_setup.sh does it (into a scratch folder)"
A=/workspace/yume/range_v1_archive/range_build.tar; mkdir -p $T/restore
tar xf $A -C $T/restore --skip-old-files --exclude=range_build/SETUP_OK && echo "    extracted"
(cd /w && find range_build ! -type d ! -path range_build/SETUP_OK | LC_ALL=C sort) > $T/have.txt
(cd $T/restore && find range_build ! -type d | LC_ALL=C sort) > $T/got.txt
if diff $T/have.txt $T/got.txt > /dev/null; then echo "    restored $(wc -l < $T/got.txt) files = /w/range_build without SETUP_OK"; else echo "    DIFFERENT:"; diff $T/have.txt $T/got.txt | head; fi
[ ! -e $T/restore/range_build/SETUP_OK ] && echo "    SETUP_OK not restored (right)"
f=$(cd $T/restore && find range_build -type f | head -1); echo CHANGED > $T/restore/$f
tar xf $A -C $T/restore --skip-old-files --exclude=range_build/SETUP_OK 2> /dev/null; [ "$(cat $T/restore/$f)" = CHANGED ] && echo "    a second restore does not overwrite a file that is there (right)"
(cd /w/range_build && find . -type f ! -name SETUP_OK -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) > $T/sha_have.txt
rm -rf $T/restore; mkdir -p $T/restore; tar xf $A -C $T/restore --exclude=range_build/SETUP_OK
(cd $T/restore/range_build && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) > $T/sha_got.txt
cmp -s $T/sha_have.txt $T/sha_got.txt && echo "    every restored file has the sha256 of the file in /w/range_build ($(wc -l < $T/sha_got.txt) files)" || echo "    SHA MISMATCH"

say "F: the stop command (not run)"
runpodctl stop pod --help 2>&1 | sed -n '1,4p' | sed "s/^/    /"; echo "    runpodctl stop pod --help: exit ${PIPESTATUS[0]}"
[ -n "${RUNPOD_POD_ID:-}" ] && echo "    RUNPOD_POD_ID is set" || echo "    RUNPOD_POD_ID NOT set"
[ -n "${RUNPOD_API_KEY:-}" ] && echo "    RUNPOD_API_KEY is set (not shown)" || echo "    RUNPOD_API_KEY NOT set"
rm -f /workspace/yume/logs/watchdog_dryrun.txt   # a dry run's note must not be read as a stop
rm -rf $T
say WDTEST-DONE
