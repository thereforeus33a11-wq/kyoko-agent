#!/usr/bin/env bash
# Puts her into an OpenDroid source tree: the character card, the notes her notebook
# starts with, her whole library (every kisaragi*/SKILL.md of this repository), and, only
# where the owner approved them, her reference pictures (opendroid/her_refs).
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

# The wordings her starting notes had in older builds, beside the starting notes. On a
# phone that still holds one of them word for word (she never rewrote it), the app gives
# that note the current wording, once, and keeps the old text in her archive. The file is
# committed and holds no private note, so a private note is left as it is unless its exact
# earlier wording is listed. Without the file nothing is refreshed.
EARLIER=0
if [ -f "$HERE/persona/seed_notes.previous.txt" ]; then
    cp "$HERE/persona/seed_notes.previous.txt" "$DEST/seed_notes.previous.txt"
    EARLIER="$(grep -c '^[a-z].*|' "$DEST/seed_notes.previous.txt" || true)"
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

echo "Persona assets: card, $(grep -c '|' "$DEST/seed_notes.txt") starting notes ($EARLIER earlier wordings), $count library files -> $DEST"

# Her reference pictures (her masters): opendroid/her_refs is never committed. Only where the
# owner has approved them, by putting a file named APPROVED beside them, do they go into the
# build: every PNG there and provenance.json, with a list the app reads on its first start
# (assets/her_refs/manifest.json: each file's name, kind ORIGINAL or MASTER, the side of her it
# shows, its SHA-256 and where it came from). The app puts each in once, byte for byte, and
# never sets back what he changed about one. Without APPROVED nothing is copied, and a list
# from an earlier run is removed, so a build never carries pictures he has not approved.
# Only a PNG that provenance.json describes, with its SHA-256, goes in: one it does not
# describe, or describes without a hash, is left out and named (a later render or a made
# picture left beside the approved ones is never bundled as one of them). Making the list
# needs python3; a PNG whose hash differs from provenance.json stops the build.
REFS_SRC="$HERE/her_refs"
REFS_DEST="$APP/app/src/main/assets/her_refs"
rm -rf "$REFS_DEST"
if [ -f "$REFS_SRC/APPROVED" ]; then
    if ! command -v python3 >/dev/null 2>&1; then
        echo "her_refs is approved, but python3 is needed to write its list" >&2
        exit 1
    fi
    if [ ! -f "$REFS_SRC/provenance.json" ]; then
        echo "her_refs is approved, but provenance.json is missing" >&2
        exit 1
    fi
    mkdir -p "$REFS_DEST"
    python3 -I - "$REFS_SRC" "$REFS_DEST" <<'PY'
import hashlib, json, os, shutil, sys

src, dest = sys.argv[1], sys.argv[2]
with open(os.path.join(src, "provenance.json"), encoding="utf-8") as f:
    provenance = json.load(f)
described = provenance.get("files", {}) or {}
if not isinstance(described, dict):
    sys.exit("provenance.json: its files are not a list by name")
default_kind = str(provenance.get("kind", "ORIGINAL")).upper()
note = "; ".join(str(part) for part in (provenance.get("subject"), provenance.get("date")) if part)
entries = []
for name in sorted(os.listdir(src)):
    path = os.path.join(src, name)
    if not name.lower().endswith(".png") or not os.path.isfile(path):
        continue
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"\x89PNG"):
        sys.exit(f"{name} is not a PNG")
    sha = hashlib.sha256(data).hexdigest()
    about = described.get(name)
    if not isinstance(about, dict):
        print(f"Left out {name}: provenance.json does not describe it")
        continue
    if not str(about.get("sha256") or "").strip():
        print(f"Left out {name}: provenance.json gives it no SHA-256 to check it by")
        continue
    if str(about["sha256"]).strip().lower() != sha:
        sys.exit(f"{name} is not the file provenance.json describes (its SHA-256 differs)")
    kind = str(about.get("kind", default_kind)).upper()
    if kind not in ("ORIGINAL", "MASTER"):
        sys.exit(f"{name} is {kind}: only originals and masters go into the app")
    entries.append({"file": name, "kind": kind, "view": about.get("view", ""), "sha256": sha, "bytes": len(data), "note": note})
# Copied only once every picture has passed, so a build that stops carries none of them.
for entry in entries:
    shutil.copyfile(os.path.join(src, entry["file"]), os.path.join(dest, entry["file"]))
shutil.copyfile(os.path.join(src, "provenance.json"), os.path.join(dest, "provenance.json"))
with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump({"version": 1, "files": entries}, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(f"Her reference pictures: {len(entries)} approved -> {dest}")
PY
else
    echo "No APPROVED file in $REFS_SRC: no reference pictures of her go into this build."
fi

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
