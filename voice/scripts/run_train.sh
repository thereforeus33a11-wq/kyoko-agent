#!/usr/bin/env bash
# GPT-SoVITS v2ProPlus fine-tune on CPU: SoVITS (s2) then GPT (s1), configs as the webui writes them.
set -euo pipefail
cd /tmp/claude-0/research/GPT-SoVITS
source /tmp/claude-0/voice/gsv-env/bin/activate
R=$(pwd)
export PYTHONPATH="$R:$R/GPT_SoVITS:$R/GPT_SoVITS/BigVGAN:$R/tools:$R/tools/asr:$R/tools/uvr5"
export version=v2ProPlus is_half=False _CUDA_VISIBLE_DEVICES="" hz=25hz
STAGE=${1:-both}; S2_EPOCHS=${S2_EPOCHS:-8}; S1_EPOCHS=${S1_EPOCHS:-15}
mkdir -p TEMP logs/yume/logs_s2_v2ProPlus logs/yume/logs_s1 SoVITS_weights_v2ProPlus GPT_weights_v2ProPlus
python - <<PY
import json, yaml
d = json.load(open("GPT_SoVITS/configs/s2v2ProPlus.json"))
t = d["train"]
t.update(fp16_run=False, batch_size=2, epochs=int("$S2_EPOCHS"), text_low_lr_rate=0.4,
         pretrained_s2G="GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
         pretrained_s2D="GPT_SoVITS/pretrained_models/v2Pro/s2Dv2ProPlus.pth",
         if_save_latest=True, if_save_every_weights=True, save_every_epoch=4, gpu_numbers="0", grad_ckpt=False, lora_rank=32)
d["model"]["version"] = "v2ProPlus"
d["data"]["exp_dir"] = d["s2_ckpt_dir"] = "logs/yume"
d["save_weight_dir"] = "SoVITS_weights_v2ProPlus"; d["name"] = "yume"; d["version"] = "v2ProPlus"
json.dump(d, open("TEMP/tmp_s2.json", "w"))
y = yaml.load(open("GPT_SoVITS/configs/s1longer-v2.yaml"), Loader=yaml.FullLoader)
y["train"].update(precision="32", batch_size=2, epochs=int("$S1_EPOCHS"), save_every_n_epoch=5, if_save_every_weights=True,
                  if_save_latest=True, if_dpo=False, half_weights_save_dir="GPT_weights_v2ProPlus", exp_name="yume")
y["pretrained_s1"] = "GPT_SoVITS/pretrained_models/s1v3.ckpt"
y["train_semantic_path"] = "logs/yume/6-name2semantic.tsv"; y["train_phoneme_path"] = "logs/yume/2-name2text.txt"
y["output_dir"] = "logs/yume/logs_s1_v2ProPlus"
yaml.dump(y, open("TEMP/tmp_s1.yaml", "w"), default_flow_style=False)
PY
if [ "$STAGE" = both ] || [ "$STAGE" = s2 ]; then date; python -s GPT_SoVITS/s2_train.py --config TEMP/tmp_s2.json; date; echo S2-DONE; fi
if [ "$STAGE" = both ] || [ "$STAGE" = s1 ]; then date; python -s GPT_SoVITS/s1_train.py --config_file TEMP/tmp_s1.yaml; date; echo S1-DONE; fi
ls -la SoVITS_weights_v2ProPlus GPT_weights_v2ProPlus
