"""Irodori-TTS v4.1-Small on a long job list, several processes sharing it (first used for the yell set, way BY):
the range trial's irodori_speak.py settings (her four clean clips, zero shot, independent guidance, text 3.0, caption 3.0,
speaker 5.0, speaker K/V scale from the job list with min_t 0.9, sequential decode, fp32, seed 1234 + 101 j) with three additions for a long job list:
  --shard i/n   this process speaks only the jobs with j % n == i (several processes share the list)
  jobs with 0 candidates are skipped (the list holds every line so that the job index j is the line number)
  --round r     more candidates for the same jobs: seed 1234 + 101 j + 7919 r, takes named t<offset+k> where offset is
                the number of takes the job already has in the folder (round 0 = the trial's seed and names)
Usage (irodori env, cwd /w/irodori, PYTHONPATH=/w/irodori, HF_HOME=/workspace/models/hf_range HF_HUB_OFFLINE=1):
  python irodori_shards.py --jobs JOBS.tsv --out DIR [--shard 0/2] [--round 0]
JOBS.tsv: name<TAB>refset<TAB>kv_scale or -<TAB>caption or -<TAB>candidates<TAB>text
"""
import argparse, glob, os, sys, time
import soundfile as sf
from irodori_tts.inference_runtime import (InferenceRuntime, RuntimeKey, SamplingRequest,
                                           download_hf_checkpoint, resolve_cfg_scales)

RF = "/w/yume/range_proto/refs"
REFSETS = {
    "her4": [f"{RF}/v12_071_clean.wav", f"{RF}/v12_040_clean.wav", f"{RF}/v12_065_clean.wav", f"{RF}/yume_07_clean.wav"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--precision", default="fp32"); ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--shard", default="0/1"); ap.add_argument("--round", type=int, default=0)
    a = ap.parse_args()
    si, sn = map(int, a.shard.split("/"))
    ckpt = download_hf_checkpoint("Aratako/Irodori-TTS-v4.1-Small")
    rt = InferenceRuntime.from_key(RuntimeKey(
        checkpoint=ckpt, model_device="cuda", codec_repo="Aratako/Semantic-DACVAE-Japanese-32dim",
        model_precision=a.precision, codec_device="cuda", codec_precision="fp32",
        codec_deterministic_encode=True, codec_deterministic_decode=True,
        compile_model=False, compile_dynamic=False, split_rare_tokens=True))
    os.makedirs(a.out, exist_ok=True)
    jobs = [l.rstrip("\n").split("\t") for l in open(a.jobs, encoding="utf-8") if l.strip() and not l.startswith("#")]
    log = open(os.path.join(a.out, f"jobs_done_r{a.round}_s{si}.tsv"), "a", encoding="utf-8")
    for j, (name, refset, kv, caption, cands, text) in enumerate(jobs):
        if int(cands) <= 0 or j % sn != si:
            continue
        marker = os.path.join(a.out, f".done_{j:04d}_r{a.round}")
        if os.path.exists(marker):
            continue
        offset = len(glob.glob(os.path.join(a.out, f"{j:04d}_{name}_t*.wav")))
        if a.round == 0 and offset:
            continue
        caption = None if caption == "-" else caption
        kv = None if kv == "-" else float(kv)
        ct, cc, cs, _ = resolve_cfg_scales(cfg_guidance_mode="independent", cfg_scale_text=3.0, cfg_scale_caption=3.0,
                                           cfg_scale_speaker=5.0, cfg_scale=None,
                                           use_caption_condition=bool(rt.model_cfg.use_caption_condition and caption),
                                           use_speaker_condition=True)
        t0 = time.time()
        res = rt.synthesize(SamplingRequest(
            text=text, caption=caption, ref_wavs=REFSETS[refset], num_candidates=int(cands), decode_mode="sequential",
            cfg_scale_text=ct, cfg_scale_caption=cc, cfg_scale_speaker=cs, cfg_guidance_mode="independent",
            speaker_kv_scale=kv, speaker_kv_min_t=(0.9 if kv else None), seed=a.seed + j * 101 + a.round * 7919), log_fn=None)
        for k, audio in enumerate(res.audios):
            path = os.path.join(a.out, f"{j:04d}_{name}_t{offset + k}.wav")
            x = audio.detach().float().cpu().numpy()
            if x.ndim > 1:
                x = x.reshape(-1) if x.shape[0] == 1 else x.mean(axis=0)
            sf.write(path, x, res.sample_rate, subtype="PCM_16")
            log.write(f"{os.path.basename(path)}\t{name}\t{refset}\t{kv}\t{caption}\t{text}\n"); log.flush()
        open(marker, "w").close()
        print(f"[{j}] {name}: {len(res.audios)} takes in {time.time() - t0:.1f}s", flush=True)
    print("IRODORI-SHARD-DONE", a.shard, flush=True)


if __name__ == "__main__":
    sys.exit(main())
