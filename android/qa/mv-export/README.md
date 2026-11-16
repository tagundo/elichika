# Isolated Android codec validation

This closure builds a small debuggable APK from the frozen encoder Java files and a synthetic QA Activity. It uses real Android MediaCodec, MediaMuxer, MediaExtractor and decoder APIs in an API 34 x86_64 emulator. It does not contain the game, game assets or production signing material. Successful results prove this encoder backend on the recorded emulator and do not establish full MV capture, simulation, rendering, native integration or physical-device fidelity.

Run `bash build.sh` with an existing API 34 Android SDK and Java JDK, then run `bash run-emulator.sh` against one booted target (or set `ANDROID_SERIAL`). Build output and a temporary QA-only signing key remain in this directory's `build/`; the script does not download or alter SDK components. `workflow-snippet.yml` is a job integration example for a GitHub runner with those SDK components already installed. It has a 15 minute job deadline; device tests have a 480 second host deadline.

The Activity runs automatically after launch. No taps, screenshots or guessed coordinates drive the test. The runner captures its visible progress, UI hierarchy, device properties, full/crash logcat and private output/report files before uninstalling only its own QA package. The workflow's artifact upload is an integration example; no workflow dispatch or remote publication is performed by these source files.

Do not interpret a build or a missing emulator as a passed device test. Read `artifacts/files/report.json`, `artifacts/last-status.txt`, `artifacts/runner-exit-code.txt`, and the evidence captured from the actual target. HEVC may be reported unsupported only when capability discovery establishes that exact encoder configuration is unavailable; H.264 is required.
