#!/usr/bin/env bash
# DeepFilterNet in its own env, for cleaning her reference clip and the teacher's takes (dfn_clean.py).
set -euo pipefail
export UV_CACHE_DIR=/w/uvcache UV_LINK_MODE=copy
[ -x /w/dfn-env/bin/python ] || uv venv -q -p 3.11 /w/dfn-env
uv pip install -q --python /w/dfn-env/bin/python torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
uv pip install -q --python /w/dfn-env/bin/python deepfilternet soundfile numpy
/w/dfn-env/bin/python -c "from df.enhance import init_df; init_df(); print('dfn ok')"
echo SETUP-CLEAN-DONE
