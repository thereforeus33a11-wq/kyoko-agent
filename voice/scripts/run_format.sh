#!/usr/bin/env bash
# GPT-SoVITS dataset formatting (webui 1Aabc), headless, CPU, v2ProPlus.
set -euo pipefail
cd /tmp/claude-0/research/GPT-SoVITS
source /tmp/claude-0/voice/gsv-env/bin/activate
R=$(pwd)
export PYTHONPATH="$R:$R/GPT_SoVITS:$R/GPT_SoVITS/BigVGAN:$R/tools:$R/tools/asr:$R/tools/uvr5"
export version=v2ProPlus is_half=False _CUDA_VISIBLE_DEVICES="" i_part=0 all_parts=1
export inp_text=/tmp/claude-0/voice/data/yume.list inp_wav_dir="" exp_name=yume opt_dir=$R/logs/yume
export bert_pretrained_dir=GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large
export cnhubert_base_dir=GPT_SoVITS/pretrained_models/chinese-hubert-base
export sv_path=GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt
export pretrained_s2G=GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth s2config_path=GPT_SoVITS/configs/s2v2ProPlus.json
mkdir -p "$opt_dir"
python -s GPT_SoVITS/prepare_datasets/1-get-text.py
mv "$opt_dir/2-name2text-0.txt" "$opt_dir/2-name2text.txt"
python -s GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py
python -s GPT_SoVITS/prepare_datasets/2-get-sv.py
python -s GPT_SoVITS/prepare_datasets/3-get-semantic.py
{ echo -e "item_name\tsemantic_audio"; cat "$opt_dir/6-name2semantic-0.tsv"; } > "$opt_dir/6-name2semantic.tsv"
rm -f "$opt_dir/6-name2semantic-0.tsv"
echo FORMAT-DONE; ls -la "$opt_dir"
