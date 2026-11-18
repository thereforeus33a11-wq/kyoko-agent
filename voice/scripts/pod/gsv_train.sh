#!/usr/bin/env bash
# GPT-SoVITS v2ProPlus fine-tune on GPU 0: SoVITS (s2) then GPT (s1), configs as the webui writes them.
set -euo pipefail
source /w/job/scripts/env.sh
cd $R
EXP=${EXP:-yume}; GPU=${GPU:-0}; FP16=${FP16:-1}; BATCH=${BATCH:-8}
export is_half=$([ $FP16 = 1 ] && echo True || echo False) _CUDA_VISIBLE_DEVICES=$GPU CUDA_VISIBLE_DEVICES=$GPU hz=25hz
S2_EPOCHS=${S2_EPOCHS:-12}; S1_EPOCHS=${S1_EPOCHS:-15}
rm -rf logs/$EXP/logs_s2_v2ProPlus logs/$EXP/logs_s1_v2ProPlus SoVITS_weights_v2ProPlus/${EXP}_e* GPT_weights_v2ProPlus/${EXP}-e*
mkdir -p TEMP logs/$EXP/logs_s2_v2ProPlus logs/$EXP/logs_s1_v2ProPlus SoVITS_weights_v2ProPlus GPT_weights_v2ProPlus
python - <<PY
import json, yaml
d = json.load(open("GPT_SoVITS/configs/s2v2ProPlus.json"))
t = d["train"]
t.update(fp16_run=("$FP16" == "1"), batch_size=int("$BATCH"), epochs=int("$S2_EPOCHS"), text_low_lr_rate=0.4,
         pretrained_s2G="GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
         pretrained_s2D="GPT_SoVITS/pretrained_models/v2Pro/s2Dv2ProPlus.pth",
         if_save_latest=True, if_save_every_weights=True, save_every_epoch=4, gpu_numbers="$GPU", grad_ckpt=False, lora_rank=32)
d["model"]["version"] = "v2ProPlus"
d["data"]["exp_dir"] = d["s2_ckpt_dir"] = "logs/$EXP"
d["save_weight_dir"] = "SoVITS_weights_v2ProPlus"; d["name"] = "$EXP"; d["version"] = "v2ProPlus"
json.dump(d, open("TEMP/tmp_s2_$EXP.json", "w"))
y = yaml.load(open("GPT_SoVITS/configs/s1longer-v2.yaml"), Loader=yaml.FullLoader)
y["train"].update(precision=("16-mixed" if "$FP16" == "1" else "32"), batch_size=int("$BATCH"), epochs=int("$S1_EPOCHS"), save_every_n_epoch=5, if_save_every_weights=True,
                  if_save_latest=True, if_dpo=False, half_weights_save_dir="GPT_weights_v2ProPlus", exp_name="$EXP")
y["pretrained_s1"] = "GPT_SoVITS/pretrained_models/s1v3.ckpt"
y["train_semantic_path"] = "logs/$EXP/6-name2semantic.tsv"; y["train_phoneme_path"] = "logs/$EXP/2-name2text.txt"
y["output_dir"] = "logs/$EXP/logs_s1_v2ProPlus"
yaml.dump(y, open("TEMP/tmp_s1_$EXP.yaml", "w"), default_flow_style=False)
PY
date; python -s GPT_SoVITS/s2_train.py --config TEMP/tmp_s2_$EXP.json; date; echo S2-DONE
date; python -s GPT_SoVITS/s1_train.py --config_file TEMP/tmp_s1_$EXP.yaml; date; echo S1-DONE
ls -la SoVITS_weights_v2ProPlus/${EXP}_e* GPT_weights_v2ProPlus/${EXP}-e*
