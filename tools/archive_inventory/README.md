# Hosted read-only archive inventory

This finite GitHub Actions workflow proves which original downloadable game files
are actually present in the public `llsifas-elichika-static-data` TAR collection.
It does not authenticate to Internet Archive, create an item, upload game bytes,
alter the old item, build applications, or read user-installed databases.

Put these files under `tools/archive_inventory/` on an isolated source branch,
and put `asset-archive-inventory.yml` under `.github/workflows/`. A push on the
exact branch `codex/asset-archive-inventory-20261115` starts the job; manual
dispatch is also available once GitHub registers it. No repository secret is needed. The checked-in gzip
catalog is the job input; the workflow does not download the eight SQLite DBs.

The input catalog is a read-only export of the eight exact official source
profiles. It contains 42,778 unique full download units, declaring
33,018,071,348 bytes. A download unit is an entire original metapack, or a
standalone pack with no metapack parent. It preserves all eight memberships:
GL Android/iOS English/Korean/Chinese and JP Android/iOS Japanese. All memberships
were compared against the preceding audit and match exactly. The installed
42,830-file count differs by 52, but that alone does not establish which names
or memberships differ; app DB revisions or added content may explain it. The
exact installed filename list has not been compared and is not used as a
completeness target.

The plain decompressed catalog SHA256 is
`0aa7c4b4cbc70f71298c47fb378b5a2d19d25a71f39907a37d14d45d5bded0ee`.
The gzip SHA256 is
`0a06f3cd4707e2ec5b1019fc60fbfabd38fbca698b8b857798fd28b82b38df96`.
The exporter includes SHA256 fingerprints of all eight original source DBs and
never changes their rows, metadata, journals or sidecars. On Linux it advises
away the clean read cache of each closed DB before starting the next DB.

Three hosted jobs each process six parts sequentially. At most three downloads
run simultaneously, capped at 8 MiB/s each. Each job needs space for one
approximately 2 GiB TAR plus 512 MiB reserve; it deletes that part after its
proof is written. Total public source traffic for a full run is
34,116,003,840 bytes, plus any bounded retry traffic. Each part has six attempts
and a 90-minute total deadline; each worker has a 345-minute job limit. Exact
HTTP Range resumes are supported within a job. A later workflow rerun starts
with fresh runner storage and may repeat completed downloads.

Every part must match the pinned IA metadata's byte count, MD5 and SHA1 before
its members are scanned. The scanner checks all uncompressed ustar blocks,
header checksums, payload bounds, zero padding and two end markers. It rejects
truncated payloads, data after end markers, unsafe paths, links and unsupported
member types. It never extracts files. Every regular `packs/<basename>` member,
including extras, gets an actual SHA256 and original TAR byte offset.

Small per-part proof artifacts are retained for 30 days, including ordinary
failures. Aggregation requires exactly one verified proof for every one of the
18 expected TARs, with the same catalog and metadata hashes. It deduplicates
identical copies by original basename and bytes, rejects conflicting copies
or catalog-size mismatches, and reports every missing, conflicting and extra
name in `audit.json`. Unexpected extras are never added to official profiles.
An absent/timed-out worker or incomplete source leaves an `INCOMPLETE` result;
the output artifacts remain useful and the workflow fails visibly.

`official-asset-inventory` contains `inventory.json`, `audit.json`, and eight
profile manifests. Each verified object includes source part, payload offset,
size, SHA256, and every identical source location. The aggregate inventory hash
binds the manifests to that exact inventory. SHA256 describes observed archive
bytes; the original catalogs contain size declarations, not publisher hashes.

The tiny test suite is entirely synthetic:

```sh
python3 -B -m unittest -v test_hosted_inventory
```

## Concrete next upload phase, after source proof

Use only verified objects from the resulting inventory. Resolve missing official
names from a separately verified source before describing the whole official
catalog as complete. IA metadata currently also lists historical fragmented
ZIP uploads; those entries are not an independently verified complete source
and must not silently fill missing objects. Preserve the original TAR item.

For new hosting, prefer one new catalog item plus bounded new object items
rather than a single item with 42,778 files. A deterministic SHA256(pack name) modulo-64
partition gives 64 object items, currently 609 to 720 official objects each;
this stays under the stricter official 1,000-files-per-item recommendation
(https://help.archive.org/help/uploading-tips/);
the exact partition count/bytes should be reported from the verified inventory
before creation. Store each opaque original file at `packs/<basename>` in its
assigned item. Profile manifests map the logical name to that exact new item
and URL. Region/platform/language selection therefore downloads only the union
of the selected manifests, including common files automatically, independent
of the physical item grouping. The official metapacks stay intact.

An uploader should process one verified source TAR at a time, verify its pinned
outer digests again, and stream each bounded original payload range unchanged.
Before PUT, recheck member size/SHA256 and calculate Content-MD5. Refuse an
existing remote same-name object with different bytes; skip only an existing
object proven identical. Use at most two concurrent uploads, bounded retry with
backoff and Retry-After, explicit job/item byte limits, and a small resumable
journal of verified PUTs. After upload, verify remote bytes (size plus downloaded
SHA256, with IA metadata MD5 as an additional check). Publish catalog/profile
availability only after the corresponding remote objects verify. Whole-catalog
completion and individually available profiles must remain separate statuses.

No credentials belong in workflow inputs, public artifacts, logs or committed
source. Prefer an already-authorized existing narrowly scoped GitHub secret if
one exists. Otherwise a possible private authorization channel is: a hosted
worker creates an ephemeral RSA-OAEP keypair; only its public key and run ID
become an artifact; the logged-in browser encrypts the user's IA S3 credential
JSON locally to that public key; only ciphertext plus a run-specific nonce is
placed in an owned control branch; the still-running worker decrypts in memory
and uses it solely with `https://s3.us.archive.org`. The private key never leaves
the worker. Any implementation must pin the exact run/public-key fingerprint,
cap polling/expiry, avoid browser/tool outputs containing raw credentials, and
delete transient key files when the job ends. This is a design for the later
upload phase, not code active in the read-only workflow.
