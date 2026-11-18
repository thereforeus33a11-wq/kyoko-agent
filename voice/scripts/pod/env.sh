# Shared settings for the GPT-SoVITS steps on the pod.
J=/w/job; R=/w/GPT-SoVITS
source /w/gsv-env/bin/activate
export PYTHONPATH="$R:$R/GPT_SoVITS:$R/GPT_SoVITS/BigVGAN:$R/tools:$R/tools/asr:$R/tools/uvr5:$J/scripts"
export NLTK_DATA=/w/gsv-env/nltk_data version=v2ProPlus
REF=$J/data/wavs/yume_07.wav
REF_TEXT="こうやってギュッとしてたら全部分かるんだからね"
SPEAK_OPTS="--speed 1.08 --temperature 1.1 --top-k 25 --half"
