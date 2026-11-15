# Strict mixed-source IA uploader, v4

This source-only bundle preserves the frozen v1, v2, and v3 bundles. V4 development used synthetic fixtures only: no actual credentials, game-payload downloads, Archive uploads, cancellation, or workflow activation. Root owns the final hosted workflow and runtime authorization; no legacy workflow template is included here.

## Fair scheduling and diagnostics

The [official Tasks API](https://archive.org/developers/tasks.html) documents serial task execution within each item. V4 overlaps work across the 64 existing hash-bucket items rather than finishing and draining one item before starting another. One persistent pool permits one to four global tasks/futures, including ownership checks, with at most one active task per bucket. It never queues 42,830 futures. The first action for every nonempty bucket completes before any bucket's second object is submitted.

Each bucket refreshes ownership immediately before its first action. A new bucket receives one object PUT, then one-shot ownership checks run in the same bounded pool. No second file is sent until the exact v3 markers appear. Missing markers fail closed. An absent item is retried with bounded coordinator backoff; worker slots do not sleep waiting for visibility. Due ownership checks and ready PUTs alternate so neither can starve the other. First-object size/MD5 ingestion is deliberately deferred: all object PUTs across every bucket finish before the final per-bucket metadata verification. Every referenced file still passes size/MD5 verification before any profile or catalog publication.

The 96 MiB staging limit is unchanged. FIFO admission lets active small objects drain ahead of a waiting exclusive object; later small arrivals cannot starve one of the six objects larger than the budget. An oversized object still runs alone, below the unchanged 141,834,336-byte maximum. The global worker count is independent of item count and accepts only 1, 2, 3, or 4. Root selects four.

Thirty-second progress distinguishes new, durable observed PUT acknowledgements from already owned identical files, deferred old acknowledgements, and public reconciliation after an ambiguous PUT. `put_bytes` and `staged_bytes` remain transport totals and may include retries. `acknowledged_files`/`acknowledged_bytes` count data objects only, after valid 2xx/ETag and durable journal recording; index PUTs do not increment them. `verified_files` remains the fresh final metadata verification count, which can stay low during the PUT phase.

`phase_worker_seconds` contains cumulative worker time, which overlaps across four workers. `source_stage` is inclusive; its `source_open`, `source_read`, and `source_hash_write` components measure opening/redirects, response reads, and hash/write work separately. `local_verify` measures the pre-PUT reread; `s3` covers the PUT operation; `metadata` covers public metadata calls; `s3_retry_wait` covers retry backoff. Do not sum an inclusive phase and its components or interpret worker-seconds as wall time. Safe HTTP status counts expose 503 throttling, while transport failures use fixed categories such as `TIMEOUT`. Exhausted PUT retries report only the last numeric HTTP status or allowlisted category, never bodies, headers, credentials, or URL queries.

The journal identity and record format are unchanged. Root can seed the ended owned v3 session only through one explicitly pinned prior run/source/artifact and both raw journal hashes, retaining the exact full nonce, prefix, account, inventory/proof pins, and mode-700/600 protections. That static workflow gate belongs to Root; this code neither discovers arbitrary prior runs nor reruns workflows. Old acknowledged objects absent from a lagging listing are deferred without PUT or record demotion, then verified in the final global phase. The old unmarked v2 session remains forbidden. Root counts the prior v3 attempt toward the five-attempt total and allows at most four new bounded attempts.

## Ownership metadata correction

V4 retains the corrected v3 metadata header serialization, ownership-field names, and human description unchanged. The official IA client emits `x-archive-meta{index:02d}-{key}` for every metadata value and escapes underscores as double hyphens. The v2 runtime used raw underscores in its three custom marker names; the service accepted core metadata and the first object but returned no ownership markers. An acknowledged object never authorizes adopting that unmarked item.

The new fields are `elichikasession`, `elichikainventorysha256`, and `elichikaaccount`, sent through `x-archive-meta00-...`. Other item metadata uses the same official numbered format; the two source URLs use `meta00-source` and `meta01-source`. Ownership checks read only the new exact field names, with no fallback to uploader, file checksums, old marker names, or local journal state. Restarting from the unmarked v2 item requires a fresh session, prefix, and journal; that old item is left untouched. V4 can retain the already marked v3 session only through the explicit pinned seed described above.

The description now links the actual final index catalog and explains that publication follows data/profile verification. It does not permanently label the collection STAGING or claim completion while the catalog is absent. The source inventory, both proof chains, object bytes, upload checksums, concurrency bounds, and complete-target gate are unchanged. See `METADATA_HEADER_AUDIT.json` for pinned official references and the independent narrow review.

The exact target is **42,830 whole objects / 33,321,064,961 bytes**. The authoritative target wrapper's decompressed SHA256 is `e53683769dc0a382783efe0403105905d3ef461ce89664f0906c728a6cc3982c`. Original eighteen-TAR proofs cover 34,797 objects. The remaining 8,033 objects / 8,101,415,374 bytes require a separately completed full-stream proof from the public `love-live-all-stars` item. Finding their names in metadata alone never authorizes a complete-source claim.

## Proof inputs and merge

The original catalog stays unchanged, SHA256 `0aa7c4b4cbc70f71298c47fb378b5a2d19d25a71f39907a37d14d45d5bded0ee`. Every original part report retains that catalog hash and its pinned full-part MD5/SHA1/size proof. The authoritative reaggregate remains immutable:

- Base inventory SHA256: `24875b44310c51a855f8536c55a092ee05f0c5555e18446e9655f2218abc198f`.
- Base audit SHA256: `bcee508ab60e82ce62e27b1cfd69f9e987721bfe45f5d1b926a528a370e205be`.
- Supplemental metadata SHA256: `0b42b8933fed37dc458f4b5e8605b39e101d7bd2cc0cb6cd39ac4ba4d6679bf5`.

The supplemental report must have schema 1, `status: "VERIFIED"`, no issues, exact verified/expected count and byte equality, and these bindings: `source_item: "love-live-all-stars"`, `source_metadata_sha256`, `target_manifest_sha256`, and `source_inventory_sha256`. Each `objects[name]` row contains exact name/size/MD5/SHA1/SHA256 plus source `{kind: "ia_individual", item: "love-live-all-stars", name, size, md5, sha1}`. Full-stream proof SHA256 is required; there is no dynamic digest seed or size-only acceptance. Root pins the actual report SHA256, successful scan run, source commit, and downloaded artifact checksum before activating uploads.

```sh
python3 -B merge_supplement.py \
  --inventory BASE/inventory.json --audit BASE/audit.json \
  --catalog ORIGINAL/expected-catalog.json.gz \
  --metadata ORIGINAL/archive-metadata.json --part-reports ORIGINAL_PROOFS \
  --target-manifest authoritative-target-42830.json.gz \
  --target-manifest-sha256 e53683769dc0a382783efe0403105905d3ef461ce89664f0906c728a6cc3982c \
  --supplemental-metadata love-live-all-stars-metadata.json \
  --supplemental-metadata-sha256 0b42b8933fed37dc458f4b5e8605b39e101d7bd2cc0cb6cd39ac4ba4d6679bf5 \
  --supplemental-proof VERIFIED_REPORT.json \
  --supplemental-proof-sha256 ACTUAL_REVIEWED_REPORT_SHA256 \
  --output NEW_COMBINED_DIRECTORY --requested-total 42830
```

The merger revalidates all eighteen reports and reconstructs every available TAR-backed target. It rejects omitted original entries, source conflicts, supplemental overrides, foreign names, missing hashes, incomplete proof, changed target sizes, or inconsistent original run/commit provenance. Only the exact original missing-name set can be added. Original object records, reports, base inventory, and base audit are never rewritten. Fresh output contains `inventory.json`, `audit.json`, and `merge-receipt.json`; no partial output directory is published.

Combined inventory/audit keep the explicit original-proof catalog hash and authoritative target hash separately. They bind base inventory/audit hashes, supplemental metadata/report hashes, exact supplemental count/bytes and provenance. `Inputs` independently reconstructs the original TAR target names again, proving that supplemental objects exactly fill their omissions.

## Plan and explicit upload

Use the uploader's `plan` or `upload` command with the same flags above, replacing base inventory/audit with the combined files and omitting `--output`. `plan` remains local only and never reads auth. For `upload`, add `--auth-file PRIVATE/auth.json --work PRIVATE/owned-work --workers 4`. Upload refuses partial operation, a different requested total, or anything other than the exact complete 42,830-object / 33,321,064,961-byte authoritative target before reading credentials.

The auth file must contain string fields `access`, `secret`, `account`, and a stable lowercase 32-hex `session_nonce`. It must be a user-owned regular nonsymlink file with mode 600 inside a mode-700 owned directory. The work directory must also be owned mode 700. Credentials are never discovered from environment, browsers, SDK configuration, workflows, or repositories.

Original sources still use the unchanged strict HTTP 206 TAR-range path: exact offsets, range totals, Content-Length and SHA256. Supplemental sources use only the fixed HTTPS public URL `https://archive.org/download/love-live-all-stars/<safe-basename>`. They require HTTP 200, identity encoding, exact Content-Length/body size, and matching pre-proven SHA256 plus metadata-pinned MD5 and SHA1. Both public source identities are rechecked against the pinned metadata. Neither public session carries authentication. Both source item identifiers are explicitly forbidden as PUT destinations.

Every object is staged privately and opaquely, then reread before PUT and hashed again while sending. At most four global workers and 96 MiB aggregate staged bytes are permitted. Objects larger than that budget run exclusively; the hard object maximum stays 141,834,336 bytes. S3 uses only `https://s3.us.archive.org`, LOW authentication, IA hexadecimal Content-MD5, no redirects, no derivation, and at most the configured one-to-four per-thread reusable connections. A response is reused only after complete bounded consumption; failures and redirects discard it. No large SDK or whole-TAR staging is used.

The fsynced append-only journal binds both proof chains, target, prefix, account, and session. Resume skips only an owned durable record with matching remote size/MD5; differing or foreign files stop the job. Acknowledged data and index files wait for delayed metadata without another PUT. A fresh missing item is recognized by the real IA HTTP-200 `{}` response. No delete path exists. Public metadata remains eventually consistent, so only one owned session should write these identifiers.

## Publication and verification

All data must match public Archive metadata size+MD5, checked in batches per data item, before any index publication. Original source SHA256 and the IA server Content-MD5 check establish the accepted data-object integrity method; successful PUT responses also require matching MD5 ETags. Lost acknowledgements require owned journal plus matching public metadata. This does not claim an independent full remote SHA256 download of the data corpus.

Eight profile manifests are uploaded and fully downloaded for SHA256+MD5 verification first. The small global catalog is uploaded last and itself fully downloaded and verified. Schema 1 uses `document_type: "profile"` and `document_type: "catalog"`. The catalog has profile descriptors and counts, not another full copy of all records. Profile records identify their original TAR or supplemental individual source. Catalog `source_items` and supplemental proof/metadata/provenance fields identify both sources. The old DB hashes are explicitly named `source_snapshot_databases`; `target_provenance` comes from the pinned authoritative wrapper, so old DB fingerprints are never labelled as final migrated target DBs. Item descriptions attribute both public sources, link the actual index catalog for status, and assert no new license.

The hosted workflow should pin all input files and successful proof-job provenance, run merge then strict plan before introducing credentials, use at most four workers with a bounded run deadline, and preserve only safe journal/events/public receipt files for finite continuation. Credentials and staged payloads must remain outside artifact paths.

```sh
python3 -B -m unittest -v test_individual_uploader test_merge_supplement test_fair_scheduler
```

Tests cover both source formats and digest failures, exact missing-set promotion, immutable old evidence, target/provenance pins, auth isolation, protected files, no overwrite, journal recovery, bounded connection reuse, and profile/catalog ordering. No live upload behavior or account permissions were tested by this worker.
