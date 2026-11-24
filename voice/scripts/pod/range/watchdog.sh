#!/usr/bin/env bash
# Safety net for a pod left running with nobody using it (it bills by the hour): when nothing has used the pod for
# an hour, save the work, write down why, and stop the pod from inside. No voice data in this script.
#
# Every CHECK_S (300 s) it checks three things:
#   1. GPU      utilisation under GPU_MAX (5 %) in every sample of the interval (one sample each SAMPLE_S = 30 s);
#   2. load     under LOAD_MAX (2) in every 1-minute window of the interval. /proc/loadavg in a pod is the HOST's
#               load (about 30 on this host with nothing running here), so it would never be under 2: the load is
#               this container's own, the CPU cores it used per minute (cgroup cpu.stat). /proc/loadavg is only
#               the fallback when the cgroup cannot be read, and is logged beside it;
#   3. files    nothing under WATCH (/w/range_v1 /w/range_build /w/logs) changed in the last QUIET_MIN (60) minutes.
# When all three have held for IDLE_S (3600 s) straight, i.e. twelve checks in a row, it
#   a. archives /w/range_v1 and /w/range_build as $ARCH/range_v1.tar and $ARCH/range_build.tar
#      (ARCH = /workspace/yume/range_v1_archive): one after the other, under the volume lock the setup uses
#      (/w/locks/volume), written as .part, its file count checked, then renamed. An empty folder is not archived
#      (the archive there is kept), a folder unchanged since its last archive is not written again;
#   b. writes NOTE (/workspace/yume/logs/watchdog_stopped.txt, appended) with the time and the reason;
#   c. stops this pod: runpodctl stop pod $RUNPOD_POD_ID, with the pod's own injected key (RUNPOD_API_KEY).
# The container disk is wiped by the stop. To go on: start the pod and run bison_setup.sh; it brings her data, the
# envs and these two archives back.
# So with the defaults a pod is stopped two hours after its last file change (an hour until check 3 holds, then an
# hour of all three), or one hour after the GPU and CPU went quiet when the files were quiet already.
#
# If an archive cannot be written (volume full or hung), nothing is stopped at once: the work would be lost. It tries
# again at every check; after ARCHIVE_GRACE_S (21600 s = 6 h) of that it stops anyway, so a broken volume cannot keep
# the pod billing for ever. ARCHIVE_GRACE_S=0 stops at once, -1 never stops without the archives.
#
# Off:      touch /w/NO_WATCHDOG   (while it is there nothing is counted and nothing is stopped; rm it to resume)
# Dry run:  DRY_RUN=1 or --dry-run: everything but the stop (the command is logged, not run; the note goes to
#           watchdog_dryrun.txt), then it exits.
# Start:    setsid nohup bash /w/watchdog.sh > /dev/null 2>&1 < /dev/null &      (bison_setup.sh does this)
# Look:     tail /w/watchdog/watchdog.log     one line per check; /w/watchdog/pid; /w/watchdog/state
# Its log and state are in STATE (/w/watchdog), outside the watched folders: its own lines must not count as use.
set -uo pipefail
STATE=${STATE:-/w/watchdog}
if [ "${WD_LOCAL:-0}" != 1 ]; then   # bash reads a script as it runs: run a copy, so /w/watchdog.sh can be replaced
  mkdir -p "$STATE" || exit 1
  # One watchdog per STATE, checked before the copy is replaced: the one that runs is reading it. The new copy
  # comes by rename (a new file), never written over the old one.
  old=$(cat "$STATE/pid" 2> /dev/null || true)
  if [ -n "$old" ] && grep -qa "$STATE/run.sh" "/proc/$old/cmdline" 2> /dev/null; then
    echo "$(date -u +%FT%TZ) a watchdog runs already (pid $old): not started again" >> "$STATE/watchdog.log"; exit 0
  fi
  cp "$0" "$STATE/run.sh.$$" && mv -f "$STATE/run.sh.$$" "$STATE/run.sh" && WD_LOCAL=1 exec bash "$STATE/run.sh" "$@"
  exit 1
fi
[ "${1:-}" = --dry-run ] && DRY_RUN=1
DRY_RUN=${DRY_RUN:-0}
CHECK_S=${CHECK_S:-300}; SAMPLE_S=${SAMPLE_S:-30}; IDLE_S=${IDLE_S:-3600}; QUIET_MIN=${QUIET_MIN:-60}
GPU_MAX=${GPU_MAX:-5}; LOAD_MAX=${LOAD_MAX:-2}; LOAD_WIN_S=${LOAD_WIN_S:-60}
WATCH=${WATCH:-"/w/range_v1 /w/range_build /w/logs"}
ARCHIVE=${ARCHIVE:-"/w/range_v1 /w/range_build"}
ARCH=${ARCH:-/workspace/yume/range_v1_archive}
ARCHIVE_GRACE_S=${ARCHIVE_GRACE_S:-21600}; ARCH_TIMEOUT_S=${ARCH_TIMEOUT_S:-3600}; LOCK_WAIT_S=${LOCK_WAIT_S:-900}
OFF=${OFF:-/w/NO_WATCHDOG}
if [ "$DRY_RUN" = 1 ]; then NOTE=${NOTE:-/workspace/yume/logs/watchdog_dryrun.txt}; else NOTE=${NOTE:-/workspace/yume/logs/watchdog_stopped.txt}; fi
LOG=$STATE/watchdog.log; VLOCK=/w/locks/volume
CPUSTAT=${CPUSTAT:-/sys/fs/cgroup/cpu.stat}

log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
num() { printf '%d.%02d' $(( $1 / 100 )) $(( $1 % 100 )); }   # hundredths -> 1.23
dur() { if [ "$1" -lt 600 ]; then echo "$1 s"; else echo "$(( $1 / 60 )) min"; fi; }

echo $$ > "$STATE/pid"

# the pod's id and key: from the environment, else from the container's first process (never printed)
envof() { tr '\0' '\n' < /proc/1/environ 2>/dev/null | sed -n "s/^$1=//p" | head -1; }
POD=${RUNPOD_POD_ID:-$(envof RUNPOD_POD_ID)}
if [ -z "${RUNPOD_API_KEY:-}" ]; then RUNPOD_API_KEY=$(envof RUNPOD_API_KEY); fi
export RUNPOD_API_KEY
STOP=""
if command -v runpodctl > /dev/null; then
  if runpodctl stop pod --help > /dev/null 2>&1; then STOP="runpodctl stop pod"
  elif runpodctl pod stop --help > /dev/null 2>&1; then STOP="runpodctl pod stop"; fi
fi
LOAD_MAX_C=$(awk -v m="$LOAD_MAX" 'BEGIN {printf "%d", m * 100}')
WIN=$(( (LOAD_WIN_S + SAMPLE_S - 1) / SAMPLE_S )); [ $WIN -ge 1 ] || WIN=1   # samples in one minute
NS=$(( CHECK_S / SAMPLE_S )); [ $NS -ge 1 ] || NS=1                    # samples in one check
trap 'log "ended by a signal (pid $$)"; exit 0' TERM INT HUP

log "watchdog started (pid $$)$([ "$DRY_RUN" = 1 ] && echo ' DRY RUN: the stop is logged, not run'): every ${CHECK_S}s: GPU < ${GPU_MAX}%, load < $LOAD_MAX, no change under [$WATCH] in $QUIET_MIN min; all three for ${IDLE_S}s -> archive [$ARCHIVE] to $ARCH, note $NOTE, stop pod ${POD:-?}"
[ -n "$POD" ] || log "WARNING: RUNPOD_POD_ID is not set: the stop cannot work"
[ -n "$RUNPOD_API_KEY" ] || log "WARNING: RUNPOD_API_KEY is not set: the stop cannot work"
[ -n "$STOP" ] || log "WARNING: runpodctl has no stop command here: the stop cannot work"
[ -r "$CPUSTAT" ] || log "WARNING: $CPUSTAT cannot be read: the load is /proc/loadavg (the host's)"
# Read-only: is the pod's own key accepted for this pod? It asks the API for this pod's desiredStatus and nothing
# else. (runpodctl get pod cannot tell: it lists the account's pods, which a pod's key may not: "Unauthorized".)
# The key goes to curl on stdin, not on its command line. This shows the key works for this pod; that it may also
# stop it is only proved by a real stop.
key_ok() {
  printf 'Authorization: Bearer %s\n' "$RUNPOD_API_KEY" | curl -s -m 20 -X POST https://api.runpod.io/graphql -H @- \
    -H 'content-type: application/json' -d "{\"query\":\"query { pod(input:{podId:\\\"$POD\\\"}) { id desiredStatus } }\"}" 2> /dev/null \
    | grep -v rpa_ | grep -o '"desiredStatus":"[A-Z_]*"' | head -1 | cut -d'"' -f4
}
if [ -n "$STOP" ] && [ -n "$POD" ]; then
  seen=$(key_ok)
  if [ -n "$seen" ]; then log "stop command: '$STOP $POD'; the pod's own key is accepted for this pod (the API gives its desiredStatus: $seen)"
  else log "stop command: '$STOP $POD'; WARNING: the API did not give this pod to the pod's own key: the stop may fail"; fi
fi

gpu_util() {  # highest utilisation over the GPUs, in %; -1 when nvidia-smi fails
  local g
  g=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | tr -d ' ' | sort -n | tail -1)
  case "$g" in ''|*[!0-9]*) echo -1 ;; *) echo "$g" ;; esac
}
cpu_usec() {  # this container's CPU time so far, in us; -1 when the cgroup cannot be read
  [ -r "$CPUSTAT" ] || { echo -1; return; }
  awk '$1 == "usage_usec" {print $2; f = 1; exit} END {if (!f) print -1}' "$CPUSTAT" 2> /dev/null
}
host_load_c() { awk '{printf "%d", $1 * 100}' /proc/loadavg; }
changed() {  # the first thing under WATCH changed (content or name) in the last QUIET_MIN minutes, or nothing
  local d have=""
  for d in $WATCH; do [ -e "$d" ] && have="$have $d"; done
  [ -n "$have" ] || return 0
  find $have \( -mmin -"$QUIET_MIN" -o -cmin -"$QUIET_MIN" \) -print -quit 2>/dev/null
}
newest() {  # the newest file under WATCH: "<UTC time> <path>"
  local d have=""
  for d in $WATCH; do [ -e "$d" ] && have="$have $d"; done
  [ -n "$have" ] || { echo "none"; return; }
  find $have -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | { read -r t p || true; [ -n "${t:-}" ] && echo "$(date -u -d "@${t%.*}" +%FT%TZ) $p" || echo none; }
}

archive_one() {  # archive_one <folder>: $ARCH/<name>.tar, whole or not at all; one write on the volume at a time
  local d=$1 name n t0 rc got
  name=$(basename "$d"); t0=$(date +%s)
  n=$(find "$d" ! -type d 2>/dev/null | wc -l)
  if [ "$n" = 0 ]; then
    ARCH_NOTE="$ARCH_NOTE  $d: no files, nothing written ($([ -s "$ARCH/$name.tar" ] && echo "$ARCH/$name.tar kept" || echo "no archive there"))"$'\n'
    log "archive: $d has no files: nothing written"; return 0
  fi
  if [ -s "$ARCH/$name.tar" ] && [ -e "$STATE/archived.$name" ] \
     && [ -z "$(find "$d" \( -newer "$STATE/archived.$name" -o -cnewer "$STATE/archived.$name" \) -print -quit 2>/dev/null)" ]; then
    ARCH_NOTE="$ARCH_NOTE  $ARCH/$name.tar: $n files, $(du -h "$ARCH/$name.tar" | cut -f1) (unchanged since it was written $(date -u -r "$STATE/archived.$name" +%FT%TZ))"$'\n'
    log "archive: $d unchanged since its archive was written"; return 0
  fi
  mkdir -p "$ARCH" "$(dirname $VLOCK)" 2>> "$LOG" || { log "archive: cannot make $ARCH"; return 1; }
  touch "$STATE/archiving.$name"
  ( flock -w "$LOCK_WAIT_S" 9 || { echo "the volume lock $VLOCK was busy for ${LOCK_WAIT_S}s"; exit 75; }
    timeout "$ARCH_TIMEOUT_S" tar cf "$ARCH/$name.tar.part" -C "$(dirname "$d")" "$name" || exit 1
    got=$(timeout "$ARCH_TIMEOUT_S" tar tf "$ARCH/$name.tar.part" | grep -vc '/$')
    [ "$got" = "$n" ] || { echo "$ARCH/$name.tar.part lists $got files, $d has $n"; exit 1; }
    mv -f "$ARCH/$name.tar.part" "$ARCH/$name.tar"
  ) 9> "$VLOCK" >> "$LOG" 2>&1
  rc=$?
  if [ $rc != 0 ]; then
    rm -f "$ARCH/$name.tar.part" 2> /dev/null
    log "archive: $d -> $ARCH/$name.tar FAILED (exit $rc)"; return 1
  fi
  mv -f "$STATE/archiving.$name" "$STATE/archived.$name"
  ARCH_NOTE="$ARCH_NOTE  $ARCH/$name.tar: $n files, $(du -h "$ARCH/$name.tar" | cut -f1), written in $(( $(date +%s) - t0 )) s (file count checked)"$'\n'
  log "archive: $d -> $ARCH/$name.tar: $n files, $(du -h "$ARCH/$name.tar" | cut -f1), $(( $(date +%s) - t0 )) s"
}
archive_all() {
  local d rc=0
  ARCH_NOTE=""
  for d in $ARCHIVE; do archive_one "$d" || { rc=1; ARCH_NOTE="$ARCH_NOTE  $d: NOT ARCHIVED (see $LOG)"$'\n'; }; done
  return $rc
}
note() {  # note <headline>: one block appended to NOTE (the volume), and to the log folder
  { echo "=== $(date -u +%FT%TZ) watchdog on pod ${POD:-?} ($(hostname))$([ "$DRY_RUN" = 1 ] && echo ' -- DRY RUN, nothing was stopped')"
    echo "$1"
    echo "Why: nothing used the pod for $(dur $IDLE_FOR) straight (checked every ${CHECK_S}s, limit $(dur "$IDLE_S")):"
    echo "  GPU utilisation: highest sample in the last check $GMAX % (limit under $GPU_MAX %)"
    echo "  load: this container used at most $(num $LMAX) CPU cores in any minute of the last check (limit under $LOAD_MAX; the host's loadavg $(num "$(host_load_c)") is not the pod's)"
    echo "  files: nothing under $WATCH changed in the last $QUIET_MIN minutes; newest file: $(newest)"
    echo "Archives:"
    printf '%s' "$ARCH_NOTE"
    echo "The container disk (/w) is wiped by the stop. To go on: start the pod, then run"
    echo "  mkdir -p /w/logs && setsid nohup bash /workspace/yume/setup/bison_setup.sh > /w/logs/bison_setup.log 2>&1 < /dev/null &"
    echo "(her data, the envs and the two archives come back; then range/bison_smoke.sh)."
  } > "$STATE/note.txt"
  cat "$STATE/note.txt" >> "$STATE/notes_all.txt"
  mkdir -p "$(dirname "$NOTE")" 2>> "$LOG" && cat "$STATE/note.txt" >> "$NOTE" 2>> "$LOG" || { log "note: could NOT write $NOTE (kept in $STATE/note.txt)"; return 1; }
  log "note: appended to $NOTE"
}
stop_pod() {
  local out rc
  if [ "$DRY_RUN" = 1 ]; then log "DRY RUN: would now run: $STOP $POD   (not run)"; return 0; fi
  [ -n "$STOP" ] && [ -n "$POD" ] || { log "stop: no stop command or no pod id: NOT stopped"; return 1; }
  log "stop: running: $STOP $POD"
  out=$($STOP "$POD" 2>&1); rc=$?
  out=$(echo "$out" | grep -v rpa_ | tr '\n' ' ' | cut -c1-300)
  log "stop: exit $rc: $out"
  echo "stop command '$STOP $POD' at $(date -u +%FT%TZ): exit $rc: $out" >> "$NOTE" 2> /dev/null
  return $rc
}

declare -a TS US   # rolling samples: time (us) and the container's CPU time (us)
idle_since=0; arch_fail_since=0; GMAX=-1; LMAX=0; IDLE_FOR=0; ARCH_NOTE=""
while :; do
  GMAX=-1; LMAX=0
  for (( k = 0; k < NS; k++ )); do
    sleep "$SAMPLE_S" & wait $!   # wait: a signal ends it at once
    g=$(gpu_util); [ "$g" -gt "$GMAX" ] && GMAX=$g
    u=$(cpu_usec); t=$(( $(date +%s%N) / 1000 ))
    TS+=("$t"); US+=("$u")
    n=${#TS[@]}
    if [ "$u" -ge 0 ] && [ "$n" -gt "$WIN" ] && [ "${US[$(( n - 1 - WIN ))]}" -ge 0 ]; then
      j=$(( n - 1 - WIN )); l=$(( (u - US[j]) * 100 / (t - TS[j]) ))
    else
      l=-1
    fi
    [ "$u" -ge 0 ] || l=$(host_load_c)                     # no cgroup: the host's loadavg
    [ "$l" -gt "$LMAX" ] && LMAX=$l
    if [ "$n" -gt $(( WIN + 4 )) ]; then TS=("${TS[@]:1}"); US=("${US[@]:1}"); fi
  done
  now=$(date +%s)
  if [ -e "$OFF" ]; then
    idle_since=0; arch_fail_since=0
    log "off: $OFF is there (nothing counted, nothing stopped)"
    echo "off since_check=$now" > "$STATE/state"; continue
  fi
  recent=$(changed)
  ok=1; why=""
  if [ "$GMAX" -ge "$GPU_MAX" ]; then ok=0; why="$why GPU"; fi
  if [ "$LMAX" -ge "$LOAD_MAX_C" ]; then ok=0; why="$why load"; fi
  if [ -n "$recent" ]; then ok=0; why="$why files"; fi
  line="GPU max $GMAX% (<$GPU_MAX) | load max $(num $LMAX) cores (<$LOAD_MAX; host loadavg $(num "$(host_load_c)")) | files: $([ -n "$recent" ] && echo "changed in the last $QUIET_MIN min: $recent" || echo "quiet for $QUIET_MIN min")"
  if [ $ok = 0 ]; then
    idle_since=0; arch_fail_since=0
    log "in use ($(echo $why | tr ' ' ,)): $line"
    echo "in_use why=$(echo $why | tr ' ' ,) check=$now" > "$STATE/state"; continue
  fi
  [ $idle_since != 0 ] || idle_since=$(( now - CHECK_S ))   # the interval just checked was idle
  IDLE_FOR=$(( now - idle_since ))
  echo "idle since=$idle_since for_s=$IDLE_FOR limit_s=$IDLE_S check=$now" > "$STATE/state"
  if [ $IDLE_FOR -lt "$IDLE_S" ]; then
    log "idle for $(dur $IDLE_FOR) of $(dur "$IDLE_S"): $line"; continue
  fi
  log "IDLE for $(dur $IDLE_FOR): $line -> archive, note, stop"
  go=1; head="The watchdog stopped this pod."
  [ "$DRY_RUN" != 1 ] || head="DRY RUN: here the watchdog would have stopped this pod."
  if archive_all; then
    arch_fail_since=0
  else
    [ $arch_fail_since != 0 ] || arch_fail_since=$now
    waited=$(( now - arch_fail_since ))
    if [ "$ARCHIVE_GRACE_S" -ge 0 ] && [ $waited -ge "$ARCHIVE_GRACE_S" ]; then
      head="The watchdog stopped this pod WITHOUT all its archives: they could not be written for $(dur $waited) (limit $(dur "$ARCHIVE_GRACE_S"))."
      [ "$DRY_RUN" != 1 ] || head="DRY RUN: $head"
      log "archive: failing for ${waited}s, limit ${ARCHIVE_GRACE_S}s: stopping without it"
    else
      go=0
      log "archive failed: NOT stopping (the work would be lost); again at the next check$([ "$ARCHIVE_GRACE_S" -ge 0 ] && echo "; stops anyway after $(( ARCHIVE_GRACE_S - waited )) more s of this")"
      # the note once, at the first failure, not at every check
      [ $waited != 0 ] || note "The watchdog wanted to stop this pod but could NOT archive the work: the pod is still running and billing." || true
    fi
  fi
  [ $go = 1 ] || continue
  if [ -e "$OFF" ]; then log "off: $OFF appeared: not stopped"; idle_since=0; continue; fi
  note "$head" || true
  if stop_pod; then
    [ "$DRY_RUN" = 1 ] && { log "DRY RUN done: exiting"; rm -f "$STATE/pid"; exit 0; }
    log "stop accepted: this container ends soon (if it is still here at the next check, the stop is tried again)"
  else
    log "STOP FAILED: the pod is still running and billing; tried again at the next check"
  fi
done
