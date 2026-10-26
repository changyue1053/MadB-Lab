# L04 pure Swift UI consumer

This independent Lab application consumes a copied public `MadBObservation`
SwiftPM source package. No producer-private source, native library, C06 framework,
or test-only SDK module is imported. `LocalStateHub` is a small independent pure
Swift state producer, with bounded per-subscription latest-state buffering.

The normal Xcode app and XCUITest target exercise three fresh SwiftUI pages and
three fresh UIKit controllers through actual navigation and accessibility taps.
SwiftUI uses its actual `onAppear`/`onDisappear`; UIKit uses actual controller
callbacks. No test calls lifecycle callbacks directly. A persistent ordinary
observer shares the source with each page. Explicit app-owned cleanup retains a
page model until `stopAndWait` succeeds; controller destruction and ARC model
release are observed separately. Page refresh and duplicate starts cannot create
new source subscriptions. Exact values are checked on the actual UI, both before
and after each page exits. Final source close is explicit and precedes simulator
cleanup.

Run the synthetic parser checks with the Lab pinned Python:

```text
python3 -B scripts/test_l04_ui.py
```

Run `scripts/verify_l04_ui.py --help` for the explicit public package, independent
file-pin digest, installed runtime, and fresh output directory arguments. The
pin is a local review input `{files: {relative_path: {sha256, size}}}`, not a new
MadB package format. The runner validates exact source bytes before copying and
after execution; local SwiftPM dependency resolution remains offline. It creates
and deletes only its own uniquely named simulator, uses a fresh DerivedData root,
and preserves command logs, source archive, app-file inventory, xcresult with
screenshots, and nonce/PID-bound target log. A failed compile or target run remains
failed even if device cleanup succeeds.

Before UI execution, a pure Swift concurrency probe pauses the source's cleanup
outside its lock. A registered close waiter must remain pending until that
cleanup returns; a second collector is rejected. The runner also applies an
explicit early-confirmation mutation to a disposable copy and requires the
specific `L04_EARLY_STOP_CONFIRMATION` rejection, rather than accepting any crash.
The positive and negative source copies and command results remain in the output.

The recipe fixes Xcode 27.0 (27A266a), Swift 6.4, and iPhoneSimulator SDK 27.0
(24A430). Runtime identity is selected from installed runtimes and recorded.
Deployment availability is iOS 17; a run on a later simulator does not certify
minimum-system behavior. No download or tool upgrade occurs.

This slice is **not** native composition, whole L04/C06 certification, C10 package
release, physical-device evidence, native late-callback/drain-failure proof,
background/rotation testing, or simultaneous-page certification. ARC release of
a local model is not proof of native cleanup.
