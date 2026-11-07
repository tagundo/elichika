# Serialized AnimationEvent experiment

This isolated QA branch loads the unchanged public GL3.12 player in a disposable
ARM64 Redroid instance. It does not change the application or provider and does
not open a personal account or device.

Three fixture byte hashes are bound by `fixtures/manifest.json`, with the exact
producer manifest retained separately. Each fixture runs in a fresh original
game process:

* baseline: existing authored Transform scales S0 and NodeScaling targets D;
* candidate: the same skeletal data plus a same-root legacy Animation, autoplay,
  Once, and a serialized `ApplyScale(float 1)` event at 0.01 seconds;
* disabled event: the same Animation/clip with the event removed.

Only the fixture-owned prefab is instantiated and later destroyed. No probe
calls NodeScaling.Initialize, ApplyScale, Animation.Play, SetActive, or a scene
constructor. Hooks are attached before instantiation, including pre-initialized
Apply calls. Natural engine frame advancement and actual per-instance identities
are required. Only owned bundles are unloaded; globally loaded game bundles are
untouched.

`unity-single-model.json` uses `COMPLETE` to mean that the bounded experiment
executed and cleaned up. That is not an event-delivery or model correctness
verdict. The separate auditor records whether the event was delivered, whether
native clip duration supports its event time, whether D was observed, and
whether both controls differed. Zero duration, stripped component accessors,
same-root Animator restrictions, missing native initialization, or an event that
does not change the model remain explicit outcomes.

Even successful standalone delivery is only feasibility evidence. It does not
establish when the actual Navi/Common/Live initializer runs, physics cache
equivalence, MV animation preservation, HOME-to-MV scene transitions, iOS, or
production packaging. Those require separate original-game scene evidence.
