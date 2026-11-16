#!/usr/bin/env bash
# Builds the Yume build of OpenDroid.
#
# It takes stock OpenDroid at one pinned commit, applies the patch in ./patch,
# copies the character card and seed notes from ./persona into the app's assets,
# and builds a debug APK. Nothing is downloaded except OpenDroid itself and what
# Gradle needs.
#
# Needs: git, JDK 21, and the Android SDK (platform 36, build-tools 36.0.0) with
# ANDROID_HOME pointing at it.
#
# Usage:  ./build.sh [work-directory]
# Output: ./out/yume-opendroid-debug.apk
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
UPSTREAM="https://github.com/JMAN730/opendroid"
COMMIT="9b471bcab61eee7151942ac4420aeec00fb62614"
WORK="${1:-$HERE/.build/opendroid}"

: "${ANDROID_HOME:?Set ANDROID_HOME to your Android SDK directory}"

# Without her card the app would build as plain OpenDroid under her name.
if [ ! -s "$HERE/persona/card.md" ]; then
    echo "persona/card.md is missing or empty" >&2
    exit 1
fi

if [ ! -d "$WORK/.git" ]; then
    mkdir -p "$WORK"
    git -C "$WORK" init -q
    git -C "$WORK" remote add origin "$UPSTREAM"
fi
git -C "$WORK" fetch -q --depth 1 origin "$COMMIT"
git -C "$WORK" checkout -q --force FETCH_HEAD
git -C "$WORK" clean -q -fd -- app/src

for patch in "$HERE"/patch/*.patch; do
    git -C "$WORK" apply --whitespace=nowarn "$patch"
done

mkdir -p "$WORK/app/src/main/assets/persona"
cp "$HERE/persona/card.md" "$WORK/app/src/main/assets/persona/card.md"
# Notes about the owner himself are kept in a file that is never committed. When it is
# there, its lines join the starting notebook of this build only.
cat "$HERE/persona/seed_notes.txt" > "$WORK/app/src/main/assets/persona/seed_notes.txt"
if [ -f "$HERE/persona/seed_notes.private.txt" ]; then
    cat "$HERE/persona/seed_notes.private.txt" >> "$WORK/app/src/main/assets/persona/seed_notes.txt"
fi

echo "sdk.dir=$ANDROID_HOME" > "$WORK/local.properties"
(cd "$WORK" && ./gradlew assembleDebug)

mkdir -p "$HERE/out"
cp "$WORK/app/build/outputs/apk/debug/app-debug.apk" "$HERE/out/yume-opendroid-debug.apk"
echo "Built: $HERE/out/yume-opendroid-debug.apk"
