#!/usr/bin/env bash
# GPT-SoVITS dataset formatting (webui 1Aabc), headless, GPU 0, v2ProPlus.
set -euo pipefail
source /w/job/scripts/env.sh
cd $R
EXP=${EXP:-yume}; GPU=${GPU:-0}; LIST=${LIST:-$J/data/yume.list}
export is_half=${HALF:-True} _CUDA_VISIBLE_DEVICES=$GPU i_part=0 all_parts=1
export inp_text=$LIST inp_wav_dir="" exp_name=$EXP opt_dir=$R/logs/$EXP
export bert_pretrained_dir=GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large
export cnhubert_base_dir=GPT_SoVITS/pretrained_models/chinese-hubert-base
export sv_path=GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt
export pretrained_s2G=GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth s2config_path=GPT_SoVITS/configs/s2v2ProPlus.json
rm -rf "$opt_dir"; mkdir -p "$opt_dir"
python -s GPT_SoVITS/prepare_datasets/1-get-text.py
mv "$opt_dir/2-name2text-0.txt" "$opt_dir/2-name2text.txt"
python -s GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py
python -s GPT_SoVITS/prepare_datasets/2-get-sv.py
python -s GPT_SoVITS/prepare_datasets/3-get-semantic.py
{ echo -e "item_name\tsemantic_audio"; cat "$opt_dir/6-name2semantic-0.tsv"; } > "$opt_dir/6-name2semantic.tsv"
rm -f "$opt_dir/6-name2semantic-0.tsv"
echo FORMAT-DONE; wc -l "$opt_dir/2-name2text.txt" "$opt_dir/6-name2semantic.tsv"
