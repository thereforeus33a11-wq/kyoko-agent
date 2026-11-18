#!/usr/bin/env bash
# After Piper ends: export her final phone voice on the pod, fetch it, score it, pack it.
# The APK build itself runs separately (build.sh), when nothing else is using the memory.
set -euo pipefail
cd /tmp/claude-0/podjob
P=$(cat pod2_id); L=/tmp/claude-0/voice/phone_final
python3 podio.py exec $P 'bash -c "O=/workspace/phone_final nohup bash /w/job/scripts/stage3.sh > /w/logs/stage3_final.log 2>&1 &"'
for i in $(seq 1 40); do
  s=$(timeout 60 python3 podio.py exec $P 'bash -c "grep -q STAGE3-DONE /w/logs/stage3_final.log && echo FIN; pgrep -f [s]tage3.sh >/dev/null || echo GONE"' 2>/dev/null || true)
  echo "$s" | grep -q -E "FIN|GONE" && break; sleep 30
done
python3 podio.py exec $P 'bash -c "grep -E \"^checkpoint|RTF|STAGE3\" /w/logs/stage3_final.log; source /w/piper-env/bin/activate; cd /w/piper1-gpl; nohup python /w/job/scripts/phone_test.py /workspace/phone_final/sherpa /w/job/data/her_test.txt /workspace/phone_final/test25 > /w/logs/test25_final.log 2>&1 &"'
for i in $(seq 1 20); do
  n=$(timeout 60 python3 podio.py exec $P 'bash -c "grep -c RTF /w/logs/test25_final.log"' 2>/dev/null || echo 0)
  [ "${n:-0}" -ge 25 ] 2>/dev/null && break; sleep 15
done
mkdir -p $L/sherpa $L/test25
for f in sherpa/model.onnx sherpa/tokens.txt ja_JP-yume-medium.onnx.json; do python3 podio.py down $P /workspace/phone_final/$f $L/$f | tail -1; done
for i in $(seq -w 0 24); do python3 podio.py down $P /workspace/phone_final/test25/00$i.wav $L/test25/00$i.wav >/dev/null; done
/tmp/claude-0/voice/gsv-env/bin/python -I /tmp/claude-0/voice/asrcheck/asr_kana.py $L/test25 /tmp/claude-0/voice/asrcheck/her_test.txt 2>/dev/null | tail -1
cd /home/user/kyoko-agent/opendroid
./tools/make_own_voice.sh $L/sherpa $L/ja_JP-yume-medium.onnx.json \
  /tmp/claude-0/voice/gsv-env/lib/python3.11/site-packages/pyopenjtalk/open_jtalk_dic_utf_8-1.11 \
  /tmp/claude-0/cmudict/cmudict.dict /tmp/claude-0/cmudict/LICENSE
echo MORNING-VOICE-READY
