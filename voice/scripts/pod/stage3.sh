#!/usr/bin/env bash
# Stage 3: export her phone voice to ONNX (fp32 + int8), make it sherpa-onnx ready, and test it the phone's way.
set -euo pipefail
J=/w/job; W=/workspace/piper-out; O=${O:-$J/out/phone}
source /w/piper-env/bin/activate
cd /w/piper1-gpl
CK=${CK:-$(ls -t $W/lightning_logs/version_*/checkpoints/last.ckpt | head -1)}
echo "checkpoint $CK"
mkdir -p $O

python -m piper.train.export_onnx --checkpoint "$CK" --output-file $O/export.onnx
python $J/scripts/sherpa_meta.py $O/export.onnx $W/ja_JP-yume-medium.onnx.json $O/sherpa
cp $O/export.onnx $O/ja_JP-yume-medium.onnx; cp $W/ja_JP-yume-medium.onnx.json $O/
python - <<PY
from onnxruntime.quantization import quantize_dynamic, QuantType
quantize_dynamic("$O/sherpa/model.onnx", "$O/sherpa/model.int8.onnx", weight_type=QuantType.QUInt8)
PY
python $J/scripts/phone_test.py $O/sherpa $J/out/eval_lines.txt $O/test | tee $O/test.txt
ls -la $O $O/sherpa
echo STAGE3-DONE
