The actual V19 run completed initial download and fetched bootstrap, then
timed out while its native Home recognizer waited for captions absent from the
real portrait layout. Its actual screenshots 110/111 show normal Home; they
do not provide managed scene, native-TID or MV qualification.

This narrow profile reads two measured regions of the same fresh original
PNG. The lower-left navigation crop uses an explicit neutral-dark pixel mask,
scale 6 and PSM 11. The School crop uses normal RGB, scale 8 and PSM 7. Exact
Shop, School, Idols and Exchange captions must all have confidence >=75 and
match the observed three-button/two-line geometry. Rank and Accessory are
excluded because the fixed-image probe did not reliably read them at >=75.
No word substitution, hint, whitelist or lower confidence threshold is used.
Raw TSV, crop, mask, scale and inverse-coordinate transforms are retained.

Two current captures must match the profile, full native Surface and every
anchor box. Both must remain fresh. Recognized modal button captions reject
eligibility; their absence does not prove that every possible modal is absent.
Original bootstrap, owned PID/start_ticks, native UnityMain selection, fresh
candidate recheck, managed Home proof and every MV assertion remain required.
The 180-second Home and 2400-second overall ends are unchanged.

CI pixel regressions retain only tiny exact navigation strips. Pixels outside
those strips are explicitly synthetic host-model context. A separate local
source-bound receipt tests the same function against untouched full actual
110/111 and the actual loading/completion/error/chooser negatives. Neither
kind of host test changes the failed V19 report or any runtime feature flag.
