#!/usr/bin/env bash
# Assembles her phone voice into opendroid/own_voice (never committed: it is a real
# person's voice), for build.sh to put into the APK.
#
#   make_own_voice.sh <sherpa dir: model.onnx + tokens.txt> <piper config .onnx.json> \
#                     <open_jtalk_dic_utf_8-1.11 dir> <cmudict.dict> <cmudict LICENSE>
#
# The Open JTalk dictionary must be the one her training labels were made with
# (open_jtalk_dic_utf_8-1.11, as pyopenjtalk 0.4.1 downloads it).
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
SHERPA="$1"; CONFIG="$2"; DIC="$3"; CMU="$4"; CMU_LICENSE="$5"
OUT="$HERE/own_voice"

for f in "$SHERPA/model.onnx" "$SHERPA/tokens.txt" "$CONFIG" "$DIC/sys.dic" "$DIC/matrix.bin" "$CMU" "$CMU_LICENSE"; do
    [ -s "$f" ] || { echo "missing: $f" >&2; exit 1; }
done

rm -rf "$OUT.tmp"
mkdir -p "$OUT.tmp/voice"
cp "$SHERPA/model.onnx" "$SHERPA/tokens.txt" "$OUT.tmp/voice/"
cp "$CONFIG" "$OUT.tmp/voice/config.json"
cp -r "$DIC" "$OUT.tmp/open_jtalk_dic_utf_8-1.11"
cp "$CMU" "$OUT.tmp/cmudict.dict"
cp "$CMU_LICENSE" "$OUT.tmp/cmudict.LICENSE"
cat > "$OUT.tmp/NOTICE" <<'EOF'
Her voice (voice/model.onnx): trained from recordings of her voice actress, used with her
agreement, for this owner's phone only. Not for redistribution.
  Fine-tuned from Piper's hifi_tts_92 medium checkpoint (CC BY 4.0): Hi-Fi Multi-Speaker
  English TTS Dataset, NVIDIA Corporation; reader 92, Cori Samuel, from LibriVox.
open_jtalk_dic_utf_8-1.11: Open JTalk dictionary (Modified BSD; see its COPYING).
cmudict.dict: The CMU Pronouncing Dictionary (BSD-style; see cmudict.LICENSE).
EOF
# The app unpacks the voice again whenever this stamp changes.
STAMP="yume-$(date -u +%Y%m%d)-$(cat "$OUT.tmp/voice/model.onnx" "$OUT.tmp/voice/tokens.txt" | sha256sum | cut -c1-12)"
echo "$STAMP" > "$OUT.tmp/VERSION"
rm -rf "$OUT"
mv "$OUT.tmp" "$OUT"
echo "Her voice: $STAMP -> $OUT ($(du -sh "$OUT" | cut -f1))"
