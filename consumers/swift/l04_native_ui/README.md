# L04 native SwiftUI consumer

This independent Lab application consumes the frozen public C06 SKIE macOS Arm64
framework and concurrency facade, plus a copied public `MadBObservation` source
package and its optional SKIE adapter. The application is an ordinary macOS app;
it imports no producer-private source and adds no native ABI or lifecycle mechanism.

One application-owned `MadBEngineHandle` serves a persistent **ordinary**
`subscribeState` / `collect` consumer and each page's `MadBStateModel`. The ordinary
consumer is not another Observation model. Its copied `MadBValueSnapshot` reaches
the MainActor through the public facade. Only the application explicitly closes
the shared owner after the ordinary subscription has stopped and drained.

The XCUITest opens three fresh SwiftUI pages with accessibility button clicks. The
real view hierarchy invokes `onAppear` and `onDisappear`; the test does not call
those callbacks. Each page checks a stable identity across refresh, rejects a
duplicate start before its factory runs, receives a native value, and leaves.
Application cleanup retains the page until `stopAndWait` succeeds. A separate weak
reference observation then confirms model release. Actual native counters must
show the ordinary subscription still active and the engine still open. A further
publication after each page leaves proves ordinary delivery continues.
Publication, session cleanup, weak-release observation and final close tasks have
explicit application owners. The close task joins earlier work and remains owned
through process exit; Quit becomes available only after native cleanup completes.

The six independent input values cover ASCII, Unicode, embedded NUL, empty text,
empty bytes and byte values including 0, 127, 128 and 255. Accessibility labels
show the exact UTF-8 and payload bytes in hexadecimal so NUL is not silently
truncated by UI accessibility. JSONL evidence retains the original text and bytes.
The final path stops the ordinary subscription, joins collection and drain,
closes the engine, checks zero native resources, and exits through the app's Quit
button. Test teardown can terminate a failed app, but that is emergency process
cleanup and does not count as native close or a passing lifecycle result.

The runner assembles a fresh project with this layout:

```text
App.swift
NativeOwner.swift
LifecycleUITests.swift
MadBL04NativeUI.xcodeproj/project.pbxproj
MadBL04NativeUI.xcodeproj/xcshareddata/xcschemes/MadBL04NativeUI.xcscheme
PublicObservation/                 # exact exported public package
PublicSkie/MadBSkie.framework/      # copied from the admitted public candidate
PublicSkie/MadBSkieConcurrency.swift
PublicSkie/MadBSkieStateSource.swift
```

Only the four quoted placeholders in the test source are substituted by the
runner: `__NONCE__`, `__PROFILE__`, `__INTERFACE__` and `__LOG_PATH__`. The values
are properly escaped Swift string literals and are passed to the app as launch
environment entries. The log path must be absolute and absent before launch.
They are test orchestration inputs, not new SDK or MadB public configuration.
The checked constructor must reject a deliberately different profile with the
existing typed `ProfileMismatch` code before the valid engine is opened.
The explicit application entry creates and retains its delegate, registers it on
`NSApplication.shared`, and runs the AppKit event loop. Before starting that loop
or constructing the native owner, it exclusively creates and synchronizes
`<log path>.process.json` with its nonce, PID and standardized absolute executable
path. This permits independent process identification if native startup fails;
the receipt is not evidence of native initialization, cleanup or acceptance.
An existing receipt is never overwritten, and the native 32-frame log is unchanged.

The project is Release, macOS Arm64, Swift 6 with complete concurrency checking
and warnings treated as errors. Deployment availability is macOS 14; running on a
later host does not certify minimum-system behavior. Dependency resolution uses
the copied local package and the admitted public framework only. Source parsing
or a successful build is not UI execution evidence; the independent runner must
retain source/candidate/tool identities, actual command logs, xcresult evidence,
the nonce/PID-bound 32-frame log and process cleanup observations.

This slice does not establish iOS, UIKit, physical-device, whole L04, C10 release,
background/rotation, simultaneous-page, event-lane, or native late-callback/fault
acceptance. Existing pure Swift iOS UI evidence and the C06 candidate's original
conclusions remain separate and unchanged.
