# E04 finite resource consumer

This independent Lab consumer uses only `package:madb_dart_ffi/madb_dart_ffi.dart`
and the approved ordinary API. It covers macOS arm64 resource values, range
rejection, explicit close, isolate transfer rejection, and exact package-asset
rejection. Each case requires a real JIT process and a real AOT process.

`MadbLibrary.open` receives the candidate's `native/` asset directory. The outer
Dart profile/2 and original C candidate profile/1 identities are checked
separately. The original C candidate is consumed from `provider/`; its original
library and identity bytes must equal the native assets. No private producer
source or developer package cache supplies an oracle or a dependency.

Run `python3 scripts/verify_e04_dart.py --help` for the exact candidate, producer,
Lab revision, official Dart SDK archive and runtime-dependency archive pins. The
runner creates its own HOME, PUB_CACHE and TMPDIR, installs pinned runtime
archives, resolves with Pub offline, analyzes, compiles AOT and runs both modes.
Only a clean frozen Lab and complete public candidate can produce target reports.
The local model tests do not execute or certify any SDK.

Five cases instantiate existing EXT-04/05/06/07/09/10 responsibilities. A failed
or missing target remains failed/missing. Byte tampering is a digest-rejection
test, not a loader-graph or native identity-mismatch test. No native allocation
counter, close-failure schedule, callback, UI, second value business,
disable/version-isolation, whole E04 or release claim is made by this slice.
Successful close is checked separately from process exit and subsequent
deletion of this invocation's private image directory. A watchdog kill never
counts as native close.
