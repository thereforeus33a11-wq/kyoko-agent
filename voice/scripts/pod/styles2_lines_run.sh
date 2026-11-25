#!/usr/bin/env bash
S=/w/range_build/styles2; JS=/w/job/scripts
source $JS/lang_env.sh; source /w/piper-env/bin/activate; cd /w/piper1-gpl
python $JS/styles2_lines.py --new $S/new_lines.txt --old $S/prev/range_build/styles/score/lines.tsv \
  --config $S/eval/voices/e1749/ja_JP-yume-medium.onnx.json --tokens $S/eval/voices/e1749/sherpa/tokens.txt \
  --train /w/job/out/v2/*/metadata*.csv /w/yume/job_out/v2/*/metadata*.csv /w/range_v1/*/ds/metadata*.csv \
  --lists $JS/range/lines_*.tsv /w/job/data/lang/lines_lang.tsv /w/job/data/her_test.txt $S/prev/range_build/styles/score/lines.tsv \
  --private /w/job/data/yume.list --out $S/lines.tsv --report $S/lines_report.json 2>&1 | grep -v '^WARNING'
