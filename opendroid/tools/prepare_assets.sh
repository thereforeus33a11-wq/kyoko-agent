#!/usr/bin/env bash
# Puts her into an OpenDroid source tree: the character card, the notes her notebook
# starts with, and her whole library (every kisaragi*/SKILL.md of this repository).
#
# The library files are copied as they are, with one change: the owner's name as it is
# written in them becomes a placeholder, so that the app fills in whatever name he gave
# it and the name itself is not what the files are searched by.
#
# Usage: tools/prepare_assets.sh <opendroid source directory>
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
APP="${1:?usage: prepare_assets.sh <opendroid source directory>}"
DEST="$APP/app/src/main/assets/persona"

if [ ! -s "$HERE/persona/card.md" ]; then
    echo "persona/card.md is missing or empty" >&2
    exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST/library"

cp "$HERE/persona/card.md" "$DEST/card.md"

# Notes about the owner himself are kept in a file that is never committed, and they
# are not put into the APK either: an APK is a file that can be copied and unpacked.
# He hands them to her on the phone (Settings, Persona, Character card, "Give her notes").
# Only with YUME_BAKE_PRIVATE_NOTES=1 do they join the starting notebook of this build.
cat "$HERE/persona/seed_notes.txt" > "$DEST/seed_notes.txt"
if [ "${YUME_BAKE_PRIVATE_NOTES:-0}" = "1" ] && [ -f "$HERE/persona/seed_notes.private.txt" ]; then
    cat "$HERE/persona/seed_notes.private.txt" >> "$DEST/seed_notes.txt"
fi

# The name the files call him by: YUME_OWNER_NAME if set, else the one in the heading
# "## With <name>" of her core file. With neither, the files are copied unchanged.
NAME="${YUME_OWNER_NAME:-}"
if [ -z "$NAME" ] && [ -f "$REPO/kisaragi/SKILL.md" ]; then
    NAME="$(sed -n 's/^## With \([A-Z][A-Za-z]*\)[[:space:]]*$/\1/p' "$REPO/kisaragi/SKILL.md" | head -n 1)"
fi
LOWER="$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]')"

count=0
for dir in "$REPO"/kisaragi*/; do
    name="$(basename "$dir")"
    [ -f "$dir/SKILL.md" ] || continue
    if [ -n "$NAME" ]; then
        sed -e "s/\b$NAME\b/{{owner}}/g" -e "s/\b$LOWER\b/{{owner_lc}}/g" "$dir/SKILL.md" > "$DEST/library/$name.md"
    else
        cp "$dir/SKILL.md" "$DEST/library/$name.md"
    fi
    count=$((count + 1))
done

if [ -f "$HERE/persona/library_index.txt" ]; then
    cp "$HERE/persona/library_index.txt" "$DEST/library_index.txt"
fi

echo "Persona assets: card, $(grep -c '|' "$DEST/seed_notes.txt") starting notes, $count library files -> $DEST"

# Her own voice (a real person's voice, used with her agreement): opendroid/own_voice is
# never committed, and only a build made where it exists carries the voice. Without it
# her lines are spoken by the phone's own voice, as before.
VOICE_SRC="$HERE/own_voice"
VOICE_DEST="$APP/app/src/main/assets/own_voice"
rm -rf "$VOICE_DEST"
if [ -f "$VOICE_SRC/VERSION" ]; then
    cp -r "$VOICE_SRC" "$VOICE_DEST"
    echo "Her own voice: $(cat "$VOICE_SRC/VERSION") -> $VOICE_DEST"
else
    echo "No voice in $VOICE_SRC: this build speaks her lines with the phone's own voice."
fi
