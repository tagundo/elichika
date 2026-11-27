This isolated source kit implements an Android MV export candidate on the exact
ARM64 GL/JP b25 clients. Protected baseline repositories, APKs, IPAs, SDKs and
uploaded files remain unchanged. The copied FovMod/DEX updater now includes the
export UI, lifecycle cancellation and Storage Access Framework result handling.
The new build_android_mv.py driver changes exactly five APK members: root
manifest date metadata, classes.dex, libil2cpp.so, libunity.so and libfovmod.so.
Every retained payload and ZIP metadata field is checked. Old camera, suit,
duplicate-character and material hooks remain in the pinned native inputs.

The user opens existing FOV settings with the two-second corner hold and selects
Export MP4. Controls offer 720p/1080p, 30/60 FPS, H.264/HEVC and a bitrate. Native
Unity-thread query resolves the exact loaded CRI cue, cached ACB/AWB paths and
waveform ID/rate/channels/sample count. The JNI bridge copies an authoritative
selection token; JSON supplied back by Java cannot redirect input file paths.
The worker decodes that exact waveform using the bundled CLHCA or scalar ADX
provider, prepares an owned anonymous/prefaulted immutable PCM mapping, then
creates the Java encoder and requests native Begin. A fresh source fingerprint
must still match the loaded song before any game-clock mutation.

The provider supports actual one-shot HCA and unencrypted ADX at 44.1/48 kHz,
mono/stereo. Unsupported loops, encryption, layouts, changed inputs and limits
fail explicitly. Logical video frames are ceil(musicLengthMs*FPS/1000); logical
PCM frames are ceil(videoFrames*sampleRate/FPS), with final silence padding.
No network service, file picker or speaker-output capture supplies the song.
Dynamic runtime SE/voice mixing is not implemented by the selected-cue decoder.

android_mv_game_bindings.cpp binds original exported IL2CPP C APIs with dlsym
and validates actual classes, methods, fields and native sidecar preimages.
All managed calls occur on the verified original Unity thread. The adapter
owns Unity ENGINE TimeManager scaled/unscaled clocks during export. Variable
frames and the custom per-invocation spring path run at 60 Hz; original Unity
fixedDeltaTime/PhysX step/cache fields remain unchanged. Both spring job buffers
are completed, solver state is snapshotted/reset, and rational ticks stop while
the bounded encoder queue applies backpressure. Retained scene/list/bone roots
and identity checks reject resource replacement. Failed job completion prevents
unsafe restoration writes and retains one bounded owner set, requiring a game
restart before another export.

Nine exact offline hooks use separate RX/RW ELF segments and 320-byte SMVAND02
sidecars. Runtime binding writes data callbacks only, never executable memory.
Original managed calls during export use the same engine's runtime_invoke
exception-out boundary and a reentry guard into original trampolines. No second
C++ exception runtime is linked. Loader initialization binds data only.

Final capture runs after the original Camera.FireOnPostRender delegate, only
for the actual final overlay CAMERA. The normal MV image-effect Behaviour must
be disabled and its target texture null. Main cameras, post-effects, stage and
overlay geometry keep their original shared-backbuffer pipeline. Real Unity
Screen.SetResolution is requested and original width/height getters must confirm
the allocated surface before tick zero. No getter advertises a false size.
Texture2D.ReadPixels synchronizes the completed native backbuffer. Bounded RGBA32
readback becomes top-down limited-range SDR Rec.709 I420 for the encoder.

AndroidMVEncoder.java uses MediaCodec and MediaMuxer with H.264 or HEVC plus
AAC-LC; AV1 is excluded. Dimensions, frame rate and bitrate are checked against
codec capabilities. Flexible YUV input must expose writable Image planes. The
producer retries the SAME data/index when offerVideo/offerAudio returns false;
input is consumed only on acceptance. Three fixed video buffers, three small
PCM buffers, a three-packet shared queue and an 8 MiB encoded-format wait bound
prevent growth with song duration. A dedicated worker owns codec/muxer calls.
No waiting for completion occurs on Unity or Android UI threads.

AAC handling prefers audited AOSP software encoders with their verified
2048-sample priming contract, or requires explicit supported delay metadata.
Explicit silent PCM flushes pending samples before EOS. AAC-LC 1024-sample
configuration and exact packet sample clocks are checked. MP4Gapless.java writes
a standard edit list trimming encoder priming and trailing padding, preserving
media offsets and exact logical movie/audio durations. It finishes the owned
partial file before final rename. Cancellation/background/destruction cancels
encoder work and requests game restoration; completion waits for the original
real render resolution. Existing/completed outputs are not overwritten. Saving
uses ACTION_CREATE_DOCUMENT; cancelling retains the private completed MP4, which
can be saved later from Settings. No broad storage permission is added.

Validation status:
- Exact GL/JP source/native hashes and hook preimages validated for four ELF
  plans; old LOADs preserved; no RWX; 288 authored Unicorn cases pass.
- Actual metadata/type-descriptor contracts cover the required game/Unity/CRI
  interfaces, including the 40-byte managed WaveformInfo out value (distinct
  from the 32-byte native CRI wire layout). Full native closure compiles/links
  for Android21 ARM64 with only libc/libm/libdl/liblog, no foreign C++ runtime.
- Portable timestamp, Rec.709/orientation/bounds, provider ownership/ADX, MP4
  structure, DEX allowlist and five-member archive-scope checks pass.
- Real one-shot encrypted HCA from the protected base APK decodes through the
  Android provider byte-identically to the existing Python/CLHCA path, including
  exact padding and anonymous-cache cleanup. This shares the CLHCA core and is
  not an independent codec implementation or an actual MV arrangement test.
- Actual Android API34 emulator QA1 FAILED: AAC was truncated/delayed. Its
  evidence remains retained. The production flush/edit-list fix is frozen at
  encoder SHA73bd83318e26224158a07b476cee6ffb84db426aaf80bd158bf3de89eece8a22.
- Actual Android QA2 run43937660066 PASSED H.264: 60 decoded frames, exact video
  PTS, barcode pixels/orientation, AAC97 packets with99328 raw samples minus2048
  delay and1280 padding =96000 presented samples; Android normal gapless decoder
  also yielded96000. Tone onset11904 vs12000 is within the strict256-sample bound.
  Both channels and cancellation pass. Both track presentation durations are2s.
- HEVC was SKIPPED because this emulator does not advertise the requested
  1280x720@30 flexible-YUV encode capability. No Android HEVC runtime pass is
  claimed. FFmpeg raw AAC decode can retain a rounded tail (96256 samples here);
  do not generalize the Android presented-sample result to every raw decoder.

Actual full-game Android loader/UI, complete MV rendering, physics, cue/mix
alignment, scene expiry, cancellation/background/out-of-space behavior and visual
parity remain runtime gates. A compiled/packaged candidate and codec test pattern
do not establish those outcomes. No finished MV export or release is claimed.

Build from the frozen source-lock-MV.json using build_android_mv.py --execute
--region GL|JP --input-apk PINNED_B25.apk --sdk ANDROID_SDK --work FRESH_OUTSIDE_KIT
--build YYYY.MM.DD.N. The driver performs no downloads, signing, installation or
publication. The stable signer and final release remain separate root actions.
Re-auditing emits separate source-audit JSON instead of overwriting frozen
augmented build profiles. The original v3 date pipeline remains a baseline tool;
this new five-member builder is the full Android MV candidate entrypoint.
