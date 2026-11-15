# Export already-built date clients individually

Source only. This kit does not download payloads locally, rebuild or sign clients,
read signing keys, install apps, or publish a release. Root must review and install
it before the hosted export workflow can run.

The immutable recipe binds successful run `43686835093`, source commit
`cb40d8337e4d986cd2918c9bb595348996c4898c`, artifact `14151027288`, its exact
344,090,806-byte length and SHA256
`4c5f938730532fe51ac9b1d215684299e7f4d8ecb07ca94fc02f202d694075a5`.

Install the source files at `ci/date_client_artifact_split/` and the workflow at
`.github/workflows/date-client-artifact-export.yml` on the isolated branch
`codex/sifas-date-artifact-export-20261115`. Creating/pushing that exact branch
starts one Ubuntu job with a 20-minute limit. It uses read-only GitHub permissions,
checks actual run and artifact API metadata, and downloads the pinned ZIP once
**on the hosted runner** using the standard GitHub CLI artifact endpoint. Its
GitHub token is not written into files or artifacts. No archive.org credentials
or Android signing secrets are referenced.

The validator checks the full ZIP hash before reading entries. Exactly five
candidate files, five proof files, SHA256SUMS and the build receipt must exist;
paths, duplicate names, encrypted entries, links and directories are rejected.
Every candidate must match its proof output, build receipt and checksum, including
the already-recorded native preservation flags. Candidate payloads are streamed
unchanged into five output directories. All original proof/receipt/checksum bytes
are retained in metadata, together with source provenance and an export manifest;
the complete metadata directory is bounded to one MiB.

Five uncompressed Actions artifacts hold the individual candidates, reducing
redundant compression work. One separately compressed metadata artifact is small
enough to inspect locally first. Android files remain **unsigned**, and IPA files
remain the previously built ad-hoc candidates. Root can retrieve one individual
artifact at a time, verify its inner-file SHA256 against the metadata, and use
the existing protected stable signer for Android before validation and release.
All six upload steps require successful validation; failed copies are never
published by this workflow.

Validation performed here: 11 tiny synthetic ZIP tests and independent source/
workflow review passed. Tests cover unchanged payload/metadata copies, outer
size/hash mismatch, wrong run/commit/status, malformed paths, duplicate ZIP or
checksum names, conflicting proofs/checksums, corrupt payloads, wrong source
locks, encrypted/link entries and output overwrite/path conflicts. No real
candidate payload was downloaded or processed here.

```sh
python -B -m unittest -v test_split_candidates
```
