#!/bin/bash
# Build an installable Android app (an APK) from mobile/, for putting on a phone without Expo Go or a laptop.
#
#     API_URL=https://staging.example.com bash scripts/build_apk.sh
#
# The API's address is built into the app. The result is mobile/android/app/build/outputs/apk/release/app-release.apk,
# for 64-bit ARM phones (every current Android phone), signed with the debug key: fine for installing by hand, not
# for a store. mobile/android is generated each time and is not kept in git.
#
# Needs, once per machine (the dev server has them; installing the SDK means accepting Google's licence for it):
#   - Node 22 on PATH (~/node/bin is added below)
#   - Java 17:                      sudo dnf install -y java-17-amazon-corretto-devel
#   - Android command-line tools in $ANDROID_HOME/cmdline-tools/latest, with the licences accepted:
#                                   $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses
#     The build downloads the platform, build tools and NDK it needs into $ANDROID_HOME by itself.
set -euo pipefail
cd "$(dirname "$0")/../mobile"
export PATH=~/node/bin:$PATH
: "${API_URL:?Set API_URL to the address of the API the app should use}"
export ANDROID_HOME=${ANDROID_HOME:-$HOME/android-sdk}
export JAVA_HOME=${JAVA_HOME:-/usr/lib/jvm/java-17-amazon-corretto}
[ -x "$JAVA_HOME/bin/java" ] || { echo "Java 17 was not found at $JAVA_HOME"; exit 1; }
[ -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ] || { echo "Android command-line tools were not found in $ANDROID_HOME"; exit 1; }

echo "=== dependencies"
npm ci --no-audit --no-fund --loglevel=error
echo "=== the Android project, generated from app.json"
EXPO_PUBLIC_API_URL=$API_URL npx expo prebuild --platform android --clean --no-install
echo "=== the app, for $API_URL"
cd android
EXPO_PUBLIC_API_URL=$API_URL NODE_ENV=production ./gradlew --no-daemon --console=plain assembleRelease \
  -PreactNativeArchitectures=arm64-v8a
ls -la app/build/outputs/apk/release/app-release.apk
