# Actual Mac Console comparison

`mac-console-performance.yml` builds C3 and the hash-bound candidate on the same Apple Silicon macOS 15 runner. It first runs all production Swift tests. The AppKit probe then hosts the complete production `RootView` and `AppModel` in a real visible window. Its temporary source projection removes exactly the application's `@main` annotation; it changes no view, polling or logging implementation.

The authenticated local fixture returns an explicitly controlled `server_running` state. It executes the exact `LogBuffer` class extracted from each corresponding Python source. This isolates native UI and bridge logging costs. It does not represent a complete bundled application launch, Go server, game login, Internet/CDN throughput, or a user's real library.

The 24 paired cases cover 0/500/1500 initial resident lines, Console visible/hidden, steady idle/bulk, and baseline/candidate. Every measurement lasts eight seconds. Bulk cases transfer eight parallel, paced 64 MiB HTTP responses through loopback and verify every received byte with SHA-256, while ingesting 250 synthetic Unicode log lines per second. Idle cases retain their initial document without new logs. All native polling goes through the production `URLSession` and `AppModel.refresh()` every 700 ms.

Reports include process CPU deltas, peak RSS, main-queue dispatch latency, model/leaf publication counts, hosting view layout/draw counts, protocol response sizes, throughput, and hashes. CPU percentages are fractions of one core, so they may exceed 100%. Paired results are single controlled samples and should be read with that sampling limit.

After timing, the patched probe uses the actual `NSTextView`: it selects and copies an existing middle line, scrolls back, applies two synchronous append batches which SwiftUI can coalesce and which remove 80 old lines, and checks selection, copied text, visible anchor and bottom-following. A missing document or failed assertion fails that case. Raw ready files, capabilities, and process output stay private and are removed before artifact export. Source receipts, compiler failures and measured results remain reviewable even when a later case fails.

Local Python checks exercise syntax, authentication, and the extracted class only. Runtime measurements require the actual Mac workflow and are never inferred from those checks.
