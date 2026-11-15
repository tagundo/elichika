# Read-only missing-object supplement

This workflow reads only the 8,033 files missing from the verified original TAR
inventory. All exact names, sizes, MD5 and SHA1 values are pinned from the public
`love-live-all-stars` Internet Archive item. Normal traffic is 8,101,415,374 bytes;
failed requests have at most three attempts. It does not download any TAR, write
game payloads to disk, authenticate to IA, create an item, or upload game bytes.

Put these sources and four gzip inputs under `tools/asset_supplement_inventory/`;
put the workflow under `.github/workflows/asset-supplement-inventory.yml`. Only a
push to `codex/asset-supplement-inventory-20261115` or manual dispatch starts it.
No repository secret is used.

Four fixed raw SHA256 input pins bind the exact public IA metadata, missing-name
map, Root's original-source coverage and authoritative 42,830-file packaged
target. The output also pins the derived 34,797-file source inventory at
`24875b44310c51a855f8536c55a092ee05f0c5555e18446e9655f2218abc198f`.
Every missing name must occur exactly once, agree with the target size, and
match the public source metadata's size, MD5 and SHA1. Private, historical,
unsafe, conflicting or omitted names fail setup before payload requests.

The reader holds at most four worker threads, eight outstanding futures and
one MiB per read. HTTP source and redirect hosts must remain public HTTPS
archive.org. Each response must be HTTP200, match any Content-Length, end at
the exact pinned size, and match both pinned digests. SHA256 is computed on
those same bytes. Partial bodies, excess bodies, HTTP errors and digest errors
get bounded retries; incomplete objects never appear in the verified map.
No caller-supplied URL is used.

The global scan deadline is 80 minutes, followed by at most one socket timeout
(45 seconds) while an active read returns. The GitHub job is capped at
90 minutes. Checkpoint proofs are written every 100 completed results, and the
final proof is written even on ordinary setup/scan failure. The artifact step
always preserves that small JSON proof. A forced runner termination may prevent
an artifact; that is a missing proof, never a success.

`supplement-proof.json` has schema1, status `VERIFIED` only when all 8,033 names
and all 8,101,415,374 bytes pass, source/target/baseline hashes, runtime CI
provenance, and `objects[name]` with size, MD5, SHA1, actual SHA256 and fixed
`source.kind=ia_individual`, `source.item=love-live-all-stars`. Any missing or
failed entry leaves `INCOMPLETE`, explicit issues, and exit1. This proof may be
merged with the original unchanged TAR proofs only after checking all pinned
bindings; the uploader must still recheck the bytes it later stages.

Tests use tiny in-memory fake HTTP responses only:

```sh
python3 -B -m unittest -v test_supplement_inventory
```
