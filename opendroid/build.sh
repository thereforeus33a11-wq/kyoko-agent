#!/usr/bin/env bash
# Builds the Yume build of OpenDroid.
#
# It takes stock OpenDroid at one pinned commit, applies the patch in ./patch, puts
# her card, her starting notes and all of her files into the app's assets, and builds
# the APK for the owner's phone. Nothing is downloaded except OpenDroid itself and
# what Gradle needs, and the pinned native parts of her voice.
#
# The APK is signed with a key of the owner's own, made on the first run and kept in
# ./keys (never committed). Keep that folder: a later build signed with the same key
# installs over the old one, so her notebook and the settings survive. A build signed
# with any other key cannot update it; Android asks to uninstall first, which removes
# everything she has written down.
#
# Needs: git, curl, JDK 21 (with keytool), and the Android SDK (platform 36, build-tools
# 36.0.0, NDK 27.2.12479018, CMake 3.22.1) with ANDROID_HOME pointing at it. Her own
# voice's native parts (Open JTalk, sherpa-onnx) are fetched at pinned versions with
# checked hashes by tools/fetch_voice_native.sh; her voice files themselves come from
# ./own_voice, which is never committed.
#
# Usage:  ./build.sh [work-directory]
# Output: ./out/yume.apk
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
UPSTREAM="https://github.com/JMAN730/opendroid"
COMMIT="9b471bcab61eee7151942ac4420aeec00fb62614"
WORK="${1:-$HERE/.build/opendroid}"

: "${ANDROID_HOME:?Set ANDROID_HOME to your Android SDK directory}"

if [ ! -d "$WORK/.git" ]; then
    mkdir -p "$WORK"
    git -C "$WORK" init -q
    git -C "$WORK" remote add origin "$UPSTREAM"
fi
git -C "$WORK" fetch -q --depth 1 origin "$COMMIT"
git -C "$WORK" checkout -q --force FETCH_HEAD
git -C "$WORK" clean -q -fd -- app

for patch in "$HERE"/patch/*.patch; do
    git -C "$WORK" apply --whitespace=nowarn "$patch"
done

"$HERE/tools/fetch_voice_native.sh" "$WORK"
"$HERE/tools/prepare_assets.sh" "$WORK"

# The owner's key: made once, then reused for every build.
KEYS="$HERE/keys"
KEYSTORE="$KEYS/yume.keystore"
PASSFILE="$KEYS/yume.password"
if [ ! -f "$KEYSTORE" ]; then
    mkdir -p "$KEYS"
    chmod 700 "$KEYS"
    (umask 077 && head -c 24 /dev/urandom | base64 | tr -d '/+=\n' > "$PASSFILE")
    keytool -genkeypair -keystore "$KEYSTORE" -storetype PKCS12 -alias yume \
        -keyalg RSA -keysize 3072 -validity 10950 \
        -storepass "$(cat "$PASSFILE")" -dname "CN=Yume build" >/dev/null 2>&1
    echo "Made a signing key in $KEYS. Keep that folder safe and private: updates need it."
fi

echo "sdk.dir=$ANDROID_HOME" > "$WORK/local.properties"
# Handed to Gradle through the environment, so the password is not on a command line.
(cd "$WORK" && \
    ORG_GRADLE_PROJECT_PERSONAL_KEYSTORE="$KEYSTORE" \
    ORG_GRADLE_PROJECT_PERSONAL_STORE_PASSWORD="$(cat "$PASSFILE")" \
    ORG_GRADLE_PROJECT_PERSONAL_KEY_ALIAS=yume \
    ./gradlew assemblePersonal)

mkdir -p "$HERE/out"
cp "$WORK/app/build/outputs/apk/personal/app-personal.apk" "$HERE/out/yume.apk"
echo "Built: $HERE/out/yume.apk"
