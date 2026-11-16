#!/usr/bin/env bash
# Writes an Ollama Modelfile that carries her card inside the model: the card becomes
# the model's own system text, with a context window large enough to hold it.
#
# What this does and does not do:
#   - `ollama run yume` on your own computer then talks as her with no app at all.
#   - Inside the Yume app it sets the context size and the samplers. The app sends her
#     card itself with every request, and a card sent with a request replaces the one in
#     the Modelfile, so the text below is not what the app runs on.
#   - It does not change the weights. Her voice held by the weights themselves is a
#     fine-tune on her own lines; opendroid/README.md says how to get there.
#
# Usage:  tools/make_modelfile.sh <base> [name-she-calls-him] [output-file]
#   <base> is what Ollama's FROM line takes: a model you already pulled (for example
#   an uncensored 12B), or a path to a .gguf file.
# Then:   ollama create yume -f <output-file>
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${1:?usage: make_modelfile.sh <base model or .gguf path> [his name] [output file]}"
OWNER="${2:-him}"
OUT="${3:-$HERE/out/Yume.Modelfile}"
CARD="$HERE/persona/card.md"

if [ ! -s "$CARD" ]; then
    echo "persona/card.md is missing or empty" >&2
    exit 1
fi
# The card goes between triple quotes; one inside it would end the block early.
if grep -q '"""' "$CARD"; then
    echo 'persona/card.md contains """, which a Modelfile cannot hold' >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"
{
    echo "FROM $BASE"
    # Her card is about 5,500 tokens; notes, pages of her files and the talk need the rest.
    echo "PARAMETER num_ctx 16384"
    echo "PARAMETER temperature 0.8"
    echo "PARAMETER top_p 0.95"
    echo "PARAMETER min_p 0.05"
    echo "PARAMETER repeat_penalty 1.0"
    echo 'SYSTEM """'
    # The owner's name is filled in here, so the file holds it: keep the output out of git.
    OWNER_ESCAPED="$(printf '%s' "$OWNER" | sed -e 's/[\/&]/\\&/g')"
    sed -e "s/{{owner}}/$OWNER_ESCAPED/g" "$CARD"
    echo '"""'
} > "$OUT"

echo "Wrote $OUT"
echo "Next: ollama create yume -f \"$OUT\""
