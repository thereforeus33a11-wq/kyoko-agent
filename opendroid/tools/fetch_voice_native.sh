#!/usr/bin/env bash
# Puts the third-party parts of her phone voice into the OpenDroid tree, from pinned
# sources with checked hashes. Nothing of these is kept in this repository.
#
#  - Open JTalk's text front end (Modified BSD), r9y9/open_jtalk at 462fc38: the commit
#    pyopenjtalk 0.4.1 is built from, which is what made her voice's training labels.
#    Built by app/src/main/cpp/CMakeLists.txt.
#  - sherpa-onnx 2.0.1 for Android (Apache-2.0; onnxruntime is MIT): the arm64 JNI
#    library, onnxruntime, and its Kotlin API (Tts.kt).
#
# Usage: fetch_voice_native.sh <opendroid work tree>
set -euo pipefail

WORK="$1"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$HERE/.build/voice-native"
mkdir -p "$CACHE"

OJT_REPO="https://github.com/r9y9/open_jtalk"
OJT_COMMIT="462fc38e7520aa89e4d32b2611749208528c901e"
SHERPA_VERSION="2.0.1"
SHERPA_TARBALL="sherpa-onnx-v$SHERPA_VERSION-android.tar.bz2"
SHERPA_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/v$SHERPA_VERSION/$SHERPA_TARBALL"
SHERPA_SHA256="39003753ec293425ed56723ea9b972b98841a490af3311670c3060548d654330"
TTS_KT_URL="https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/v$SHERPA_VERSION/sherpa-onnx/kotlin-api/Tts.kt"
TTS_KT_SHA256="291d30c045ae1cb88a87cce8d6794189e5e63f6ecefd012259694932a5594f38"

check() {  # check <file> <sha256>
    echo "$2  $1" | sha256sum -c --quiet - || { echo "Hash mismatch for $1" >&2; rm -f "$1"; exit 1; }
}

# Open JTalk source, the code directories only (not the dictionary sources).
if [ ! -d "$CACHE/open_jtalk/.git" ]; then
    git -C "$CACHE" init -q open_jtalk
    git -C "$CACHE/open_jtalk" remote add origin "$OJT_REPO"
fi
git -C "$CACHE/open_jtalk" fetch -q --depth 1 origin "$OJT_COMMIT"
git -C "$CACHE/open_jtalk" checkout -q --force FETCH_HEAD
[ "$(git -C "$CACHE/open_jtalk" rev-parse HEAD)" = "$OJT_COMMIT" ] || { echo "Open JTalk is not at $OJT_COMMIT" >&2; exit 1; }
DEST="$WORK/app/src/main/cpp/open_jtalk"
rm -rf "$DEST"
mkdir -p "$DEST/src"
for d in jpcommon mecab mecab2njd njd njd2jpcommon njd_set_accent_phrase njd_set_accent_type \
         njd_set_digit njd_set_long_vowel njd_set_pronunciation njd_set_unvoiced_vowel text2mecab; do
    cp -r "$CACHE/open_jtalk/src/$d" "$DEST/src/$d"
done
# The build uses our config.h (app/src/main/cpp/config.h), not one written on this machine.
rm -f "$DEST/src/mecab/src/config.h"
cp "$CACHE/open_jtalk/src/COPYING" "$DEST/COPYING"

# sherpa-onnx for Android: arm64 only (the owner's phone).
[ -f "$CACHE/$SHERPA_TARBALL" ] || curl -sS -L --retry 4 -o "$CACHE/$SHERPA_TARBALL" "$SHERPA_URL"
check "$CACHE/$SHERPA_TARBALL" "$SHERPA_SHA256"
LIBS="$WORK/app/src/main/jniLibs/arm64-v8a"
mkdir -p "$LIBS"
tar -xjf "$CACHE/$SHERPA_TARBALL" -C "$CACHE" ./jniLibs/arm64-v8a/libsherpa-onnx-jni.so ./jniLibs/arm64-v8a/libonnxruntime.so
cp "$CACHE/jniLibs/arm64-v8a/libsherpa-onnx-jni.so" "$CACHE/jniLibs/arm64-v8a/libonnxruntime.so" "$LIBS/"

[ -f "$CACHE/Tts.kt" ] || curl -sS -L --retry 4 -o "$CACHE/Tts.kt" "$TTS_KT_URL"
check "$CACHE/Tts.kt" "$TTS_KT_SHA256"
mkdir -p "$WORK/app/src/main/java/com/k2fsa/sherpa/onnx"
cp "$CACHE/Tts.kt" "$WORK/app/src/main/java/com/k2fsa/sherpa/onnx/Tts.kt"

echo "Voice native parts in place: Open JTalk $OJT_COMMIT, sherpa-onnx $SHERPA_VERSION (arm64-v8a)."
