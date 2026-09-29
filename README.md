# Blemm Bedrock Launcher

A Windows launcher project for running a **user-supplied Minecraft Bedrock Android APK** through an Android runtime.

## Project rules

- Minecraft is not bundled or downloaded by this project.
- The user supplies their own APK.
- The launcher does not bypass Minecraft licensing, DRM, or entitlement checks.
- Microsoft/Xbox authentication must use legitimate authentication flows.
- Microsoft passwords are never collected by the launcher.
- The launcher is infrastructure around an Android installation, not a replacement copy of Minecraft.

## Current prototype

The first milestone is:

1. Start the launcher.
2. Import and validate a user-provided APK.
3. Detect/configure an Android runtime.
4. Install the APK through ADB.
5. Authenticate through the legitimate Minecraft/Microsoft flow.
6. Launch Bedrock.

## Windows target

The initial implementation targets Windows 10/11 x64.

The Android runtime is intentionally kept separate from the launcher so that runtime options can be tested without coupling the project to one proprietary emulator.

## Status

Early prototype.
