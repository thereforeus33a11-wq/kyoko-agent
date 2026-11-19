#!/usr/bin/env bash
# Assembles her phone voice into opendroid/own_voice (never committed: it is a real
# person's voice), for build.sh to put into the APK.
#
#   [ENGLISH_TABLE=<en_ipa_table.json>] make_own_voice.sh <sherpa dir: model.onnx + tokens.txt> \
#       <piper config .onnx.json> <open_jtalk_dic_utf_8-1.11 dir> <cmudict.dict> <cmudict LICENSE>
#
# The Open JTalk dictionary must be the one her training labels were made with
# (open_jtalk_dic_utf_8-1.11, as pyopenjtalk 0.4.1 downloads it).
#
# ENGLISH_TABLE: only for a voice trained on her English as English phonemes (stage2_lang.sh),
# and it must be the very en_ipa_table.json that voice was trained with (the pod bundle's
# scripts/en_ipa_table.json). That table is shipped, and voice/config.json says the voice reads
# it ("yume_english", with the table's SHA-256), so the app says her English as English
# (core/voice/own/BilingualVoice.kt). Without it the voice reads English the katakana way, as
# every earlier voice of hers does; the repository's table is shipped all the same.
# OWN_VOICE_OUT: where to assemble it (default opendroid/own_voice).
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
SHERPA="$1"; CONFIG="$2"; DIC="$3"; CMU="$4"; CMU_LICENSE="$5"
OUT="${OWN_VOICE_OUT:-$HERE/own_voice}"
# How her English is read (shared with her training: voice/scripts/pod/en_ipa_table.json).
TABLE="${ENGLISH_TABLE:-$HERE/../voice/scripts/pod/en_ipa_table.json}"

for f in "$SHERPA/model.onnx" "$SHERPA/tokens.txt" "$CONFIG" "$DIC/sys.dic" "$DIC/matrix.bin" "$CMU" "$CMU_LICENSE" "$TABLE"; do
    [ -s "$f" ] || { echo "missing: $f" >&2; exit 1; }
done

rm -rf "$OUT.tmp"
mkdir -p "$OUT.tmp/voice"
cp "$SHERPA/model.onnx" "$SHERPA/tokens.txt" "$OUT.tmp/voice/"
cp "$CONFIG" "$OUT.tmp/voice/config.json"
cp -r "$DIC" "$OUT.tmp/open_jtalk_dic_utf_8-1.11"
cp "$CMU" "$OUT.tmp/cmudict.dict"
cp "$CMU_LICENSE" "$OUT.tmp/cmudict.LICENSE"
cp "$TABLE" "$OUT.tmp/en_ipa_table.json"
# The table names the CMU dictionary it was made with; a different one would read her English differently.
WANT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["cmudict"]["sha256"])' "$TABLE")
[ "$(sha256sum "$CMU" | cut -d' ' -f1)" = "$WANT" ] || { echo "cmudict.dict is not the one en_ipa_table.json was made with" >&2; exit 1; }
# Whether the voice says her English as English: written into its config, or taken out of it.
python3 - "$OUT.tmp/voice/config.json" "$OUT.tmp/en_ipa_table.json" "$OUT.tmp/voice/tokens.txt" "${ENGLISH_TABLE:+bilingual}" <<'PY'
import hashlib, json, sys
cfg_path, table_path, tokens_path, bilingual = sys.argv[1:5]
cfg = json.load(open(cfg_path, encoding="utf-8"))
cfg.pop("yume_english", None)
if bilingual:
    t = json.load(open(table_path, encoding="utf-8"))
    # Every symbol the table can give must be a token of the voice (BilingualVoice.symbols).
    texts = list(t["vowels"].values()) + list(t["consonants"].values()) + list(t["stress_marks"].values())
    texts += [v for d in t["vowels_by_stress"].values() for v in d.values()]
    texts += [v for d in t["r_vowel_before_vowel"]["vowels"].values() for v in d.values()]
    texts += [w["ipa"] for w in t["weak_forms"]["words"].values()]
    texts += [w["strong"] for w in t["weak_forms"]["words"].values() if "strong" in w]
    texts += [t["boundaries"][k] for k in ("word", "clause", "after_clause", "switch", "sentence_end_default")]
    texts += list(t["segmentation"]["terminal_punct"].values())
    tokens = {l.rstrip("\n").rpartition(" ")[0] for l in open(tokens_path, encoding="utf-8") if l.strip("\n")}
    missing = sorted({c for s in texts for c in s} - tokens)
    if missing:
        sys.exit(f"the voice has no token for {missing}: not the voice this table was trained into")
    cfg["yume_english"] = {
        "phonemes": "en_ipa_table", "table": t["name"], "table_version": t["version"],
        "table_sha256": hashlib.sha256(open(table_path, "rb").read()).hexdigest(),
    }
json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("Her English:", "as English (en_ipa_table.json, %s)" % cfg["yume_english"]["table_sha256"][:12] if bilingual else "katakana")
PY
cat > "$OUT.tmp/NOTICE" <<'EOF'
Her voice (voice/model.onnx): trained from recordings of her voice actress, used with her
agreement, for this owner's phone only. Not for redistribution.
  Fine-tuned from Piper's hifi_tts_92 medium checkpoint (CC BY 4.0): Hi-Fi Multi-Speaker
  English TTS Dataset, NVIDIA Corporation; reader 92, Cori Samuel, from LibriVox.
open_jtalk_dic_utf_8-1.11: Open JTalk dictionary (Modified BSD; see its COPYING).
cmudict.dict: The CMU Pronouncing Dictionary (BSD-style; see cmudict.LICENSE).
en_ipa_table.json: how her English is read (made for this voice).
EOF
# The app unpacks the voice again whenever this stamp changes.
STAMP="yume-$(date -u +%Y%m%d)-$(cat "$OUT.tmp/voice/model.onnx" "$OUT.tmp/voice/tokens.txt" "$OUT.tmp/voice/config.json" "$OUT.tmp/en_ipa_table.json" | sha256sum | cut -c1-12)"
echo "$STAMP" > "$OUT.tmp/VERSION"
rm -rf "$OUT"
mv "$OUT.tmp" "$OUT"
echo "Her voice: $STAMP -> $OUT ($(du -sh "$OUT" | cut -f1))"
