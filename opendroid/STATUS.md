# Yume: where everything stands (24 Nov 2026, 12:30 UTC)

This page and checkpoint 04 on his Drive (the same text, with the app bundle and the work packs beside it) are enough to carry on from this point in a new session.

## Where everything lives

| What | Where | Survives |
|---|---|---|
| Plans, principles, voice scripts, her library pages | GitHub, branch `ccr-ad7b35b0-0uv0hf`, commit `d74f743` (public: no voice data, no keys) | Yes |
| The app's code: every branch (29) | `yume-app.bundle` on his Drive (checkpoint 04). Restore below | Yes (Drive) |
| Big voice files (style sets, sound bank, checkpoints, her teacher, caches) | Runpod network volume `pzgwdzite9` (EUR-IS-1), `/workspace/yume/` | Yes, as long as the volume is kept. Stopping or deleting the pod does not delete it |
| The session's working files (findings, briefs, job scripts) | `session-work.tgz` on his Drive (checkpoint 04) | Yes (Drive) |
| Private voice notes and job lists (no audio) | `voice-private-notes.tgz` on his Drive (checkpoint 04) | Yes (Drive) |
| Sample packs (audio) | Sent to him in the chat; also on the volume and on the build machine | Chat copies |

## The app's code

- `yume-app.bundle` (SHA-256 `56f2b8fdf9af15a1926b322ed4e43ba294ef511606c2d40f50f271499642ef1b`). A git bundle of all 29 branches, relative to upstream OpenDroid commit `9b471bcab61eee7151942ac4420aeec00fb62614`.
  - To restore: `git clone https://github.com/JMAN730/opendroid app && cd app && git fetch ../yume-app.bundle 'refs/heads/*:refs/heads/*'`.
  - The app's build-time assets come from GitHub through `opendroid/tools/prepare_assets.sh`. Her voice files come from her voice pack (`opendroid/own_voice`, never committed; it is on the build machine and on the volume as `phone_lang2`).
- Branch heads at this checkpoint:
  - `yume` `db3ae3e`: Phase 1 (no turns) merged. Not shipped yet: the principles gate found 35 problems.
  - `g1` `67e4200`: the gate fixes, all five fix branches and `c1-counts` merged into one. It is in its first independent re-review; the bundle holds it at `7362c30`.
  - `g1-uncommitted.patch` (`17a071a4...`): the re-review fixer's edits that were not yet committed at 12:28 UTC, against `7362c30`.
  - Fix branches: `g1-words` `1723b5d`, `g1-sound` `5a27501`, `g1-one` `faab256`, `g1-lines` `7a366c7`, `g1-told` `44c4ad7`, `c1-counts` `4d9fa56`.
- The APK on his phone is still the Phase 0 build of 21 Nov.

## The pod

- Pod `k0a4mlqctehiv8` ("yume-range", one RTX PRO 6000 Blackwell, $2.69 an hour).
- It is training her phone voice with five styles: 0 normal, 1 soft, 2 whisper, 3 loud, 4 yell. The run was at epoch 1099 at 12:28 UTC, of a run of at most 8 hours that started from her chosen voice e974.
  - It runs detached on the pod, so it does not need this session.
  - Each kept checkpoint is copied to `/workspace/yume/piper-styles-keep/` as it lands (`keep-epoch=1099.ckpt` and the warm start `ws_e974_styles.ckpt` were there at 12:28).
- Round 3 of her sound bank (her two laughs, refills, whispers) also runs on it.
- **The watchdog** (`/w/watchdog.sh`, pid 22495) does the following when the GPU has been idle and nothing has changed for an hour (about two hours after the last file change):
  1. archives `/w/range_v1` and `/w/range_build` to `/workspace/yume/range_v1_archive/`;
  2. writes `/workspace/yume/logs/watchdog_stopped.txt`;
  3. stops the pod from inside, with the pod's own key.
  - Runpod documents that key as scoped to the pod itself. A real stop has not yet been seen, so this session also has check-ins scheduled to stop the pod.
- Before restarting work on the pod: start it, then run `bison_setup.sh` (it restores everything from the volume in about 2 minutes).

### On the volume, `/workspace/yume/` (sizes at 12:28 UTC)

- `range_v1_archive/` 1.7 GB: soft, whisper, loud and yell sets, each independently checked (864 / 930 / 912 / 857 clips); `sounds.tar` (her sound bank, rounds 1 and 2: 342 takes), `sounds_r1.tar`, `sounds_r2.tar`.
- `range_build/` 2.4 GB (build folders), `piper-styles-keep/` 1.6 GB (the training's checkpoints), `cache/` 19 GB (package cache for a fast restore), `models/` 9.3 GB, `xfer.tar` 11.3 GB (her whole data pack from before), her teacher voice and her phone voice.

## Jobs running when this was taken (they continue while this session has usage)

1. **The principles gate fixes** (35 findings): first independent re-review. Then merge into `yume`.
2. **Her phone voice with five styles**: training, then scoring against her voice today (her normal voice must be no worse), then an independent check. It ships only if her normal voice is no worse.
3. **Her two laughs** (sound bank round 3), then an independent check.
4. **Her as a whole person**: maps her canon, checks it against all a real person has, fills the gaps from her canon (a new library page, `kisaragi-depth`), and has four critics check it. Output: `scratchpad/person/`.
5. **The gap map v2**: every human faculty, every route (proven, experimental, hypothetical, combined), prototypes, an ambition critic, and build briefs. Output: `opendroid/GAP_MAP.md` and `BUILD_BRIEFS.md`.

## Written and waiting (job scripts in `session-work.tgz`)

- `choices.js`: nothing obliges her to answer or react, and her own mind stays hers. Starts when the gate fixes merge. Its sweep is done.
- `os01.js`: the phone plan's OS0 and OS1 (staying alive, his Stop as sleep, why she stopped, a crash log with no words).
- Then: his answers (her age by date, tiredness, tears, memory that fades the way a person's does), the styles and sounds in the app, and the APK.

## His words today, now in `opendroid/HER_PRINCIPLES.md`

- The aim: as close to a real person as she can get; nothing ruled out.
- Nothing obliges her to answer or react.
- Her own mind: her opinions, sides and faults are hers.
- His answers: she ages (birthday August 19, 2007), she can cry, small details fade the way a person's do, and she gets tired.
- The gate now has 9 checks.

## To carry on in a new session

1. Read `opendroid/HER_PRINCIPLES.md`, then this file.
2. Restore the app from the bundle. Apply `g1-uncommitted.patch` on `g1` at `7362c30` if `g1` has not moved past it.
3. Check the pod: is it stopped (`/workspace/yume/logs/watchdog_stopped.txt`), and where did training get to (`piper-styles-keep/`)?
4. Re-run any job that did not finish from its script in `session-work.tgz` (`wfscripts/` and the top-level `.js` files). Each one says what it needs and what it writes.
