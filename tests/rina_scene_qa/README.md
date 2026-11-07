# Original Unity scene-model investigation

This manual-only QA branch starts a fresh ARM64 Redroid container and installs
the unchanged public GL3.12.0 client. It does not use a physical device, user
backup, existing account, private database, or product build. It creates no
release or pull request.

The pinned Frida bridge invokes the original player's existing asynchronous
AssetBundle APIs through UnitySynchronizationContext.Post. Each case starts a
fresh game process. Only test-owned prefab assets receive Initialize() and five
ApplyScale(1) calls; only bundles loaded by this probe are unloaded.

The strict cases require full CAB+bundle-name Navi rebasing to coexist with MV
board in both orders and with all three roles at once. Two shared-CAB controls
must detect a collision. CAB-only cases record whether CAB identity alone is
enough; their observation does not establish a game-scene guarantee. Every
successful prefab verifies exact BreastSize/HipsSize targets after all five
applications, retains independent native object identities, and preserves the
already-loaded role after the next role loads. Texture dimensions are recorded;
this does not demonstrate texture rendering or original-client physics.

`fixtures/producer-manifest.json` retains the supplied read-only provenance.
`fixtures/manifest.json` selects the six Android fixtures and binds the cases.
The original control's target is its actual immutable serialized original Node
values rather than the diagnostic D used by the other five fixtures. All fixture
bytes and installed game APK are hashed before and after execution.

This probe establishes native bundle co-load and scaler behavior only. Actual
HOME/Navi to MV scene selection, dependencies, routing fallback, initialization
physics, CAB coexistence with unrelated game assets, and iOS runtime behavior
remain separate checks.
