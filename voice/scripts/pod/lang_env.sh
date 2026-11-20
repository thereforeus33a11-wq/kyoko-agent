# Shared settings for her English steps on the pod (source it after setup.sh and setup_lang.sh).
J=/w/job; R=/w/GPT-SoVITS
export CMUDICT=$J/data/cmudict.dict PIPER_SRC=/w/piper1-gpl/src
LANG_IN=$J/data/lang                # lines_lang.tsv and speak_lang.txt (lang_lines/out in the repo)
OL=$J/out/lang                      # outputs, on the saved volume (/w/job/out -> /workspace/job_out)
TEACHER=${TEACHER:-/workspace/teacher}
G_HER=${G_HER:-$(ls $TEACHER/*e10*.ckpt 2>/dev/null | head -1)}
S2=${S2:-$(ls $TEACHER/*e12*.pth 2>/dev/null | head -1)}
G_BASE=${G_BASE:-$R/GPT_SoVITS/pretrained_models/s1v3.ckpt}
# Her real Japanese clips that take turns as the teacher's reference: calm to lively, not the
# brightest or cutest. Their texts come from data/yume.list.
REFS_LANG=${REFS_LANG:-"yume_07 v12_040 v12_065 v12_071"}
SPEAK_LANG_OPTS=${SPEAK_LANG_OPTS:-"--speed 1.0 --temperature 1.0 --top-k 20 --half"}
WHISPER=${WHISPER:-/workspace/models/faster-whisper-large-v3}
WAVLM=${WAVLM:-/workspace/models/wavlm-base-plus-sv}
JA_DS=${JA_DS:-$J/out/ds}           # her Japanese training set from stage 1 (wavs + metadata.csv)
gsv() { (source /w/gsv-env/bin/activate; export PYTHONPATH="$R:$R/GPT_SoVITS:$R/GPT_SoVITS/BigVGAN:$R/tools:$J/scripts" NLTK_DATA=/w/gsv-env/nltk_data version=v2ProPlus; cd $R; "$@"); }
asr() { (export LD_LIBRARY_PATH="$(/w/asr-env/bin/python -c 'import os, nvidia.cublas.lib, nvidia.cudnn.lib; print(list(nvidia.cublas.lib.__path__)[0] + ":" + list(nvidia.cudnn.lib.__path__)[0])'):${LD_LIBRARY_PATH:-}"; /w/asr-env/bin/python "$@"); }
make_refs() {  # make_refs <out.tsv>: "clip.wav<TAB>text" for REFS_LANG
  : > "$1"
  for c in $REFS_LANG; do
    t=$(grep -F "/$c.wav|" $J/data/yume.list | head -1 | cut -d'|' -f4)
    [ -n "$t" ] && [ -s $J/data/wavs/$c.wav ] && printf '%s\t%s\n' "$J/data/wavs/$c.wav" "$t" >> "$1"
  done
  [ -s "$1" ] || { echo "no reference clips found for: $REFS_LANG" >&2; return 1; }
}
