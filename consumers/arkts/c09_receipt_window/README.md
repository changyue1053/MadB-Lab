# C09 after physical ACK, before Runtime receipt

This supplement independently consumes a newly frozen public test companion with
`testBeforeRuntimeReceipt(runtime, probe)`. It uses the approved synchronous
callback cutpoint and public observation helpers only. It neither changes native
owners nor replaces physical ACK/receipt predicates. The older C07 candidates and
the existing before-ACK supplement retain their original scope.

The normal case performs real original-runtime work, checks wrong-wrapper,
nonfunction, duplicate, closing and closed registration errors, and enters the
one-shot callback. It archives the complete native178/facade15 frames or
Kotlin110/settlement9/admission13 frames. The independent oracle requires physical
owners to be retired, lifetime pairs balanced, receipt still unconsumed, original
close pending inside its tick, and typed rejection of `openRuntime()`. Reentrant
close must be the same Promise. After callback return, the original close must
consume the receipt; a new Runtime must execute actual work and close.

`NegativeProbes.js` is a Lab-owned JavaScript seam for malformed/nonvoid values
ArkTS cannot faithfully represent. It receives only public closures; it imports
no SDK internals. Its `.d.ts` describes the callback transport, not permission to
return a Promise. Separate fresh processes return a Promise or a thenable whose
`then` getter must remain unread, throw a retained original Error, throw an Error
whose `code` getter would throw, and throw `undefined` or an object whose Proxy
prototype-classification trap throws. The Error cases must retain identity;
non-Error and classification failures must reject with existing `CallbackFailure`.
The getter must remain unread, while the Proxy classification trap must run
exactly once. Complete observation frames after two further owner-loop turns
must still show receipt zero, no timer or in-flight tick, one callback invocation
and the same rejected close Promise/failure. Each must
reject the actual close while the receipt remains unconsumed. A successful
negative observation means that expected rejection was observed; it never means
normal close or SDK cleanup succeeded. Process stop/uninstall is separate device
recovery. A test assertion caught inside the normal callback is rethrown after
awaiting the original close so it does not obstruct that close path.

Run host oracle checks with pinned Python, then claim the target through the main
coordinator and provide independently frozen candidate digests:

```sh
python3 -B -m unittest discover -s harness -p c09_receipt_window_tests.py
python3 -B harness/c09_receipt_window.py \
  --route c \
  --candidate /absolute/path/to/new/c-test/candidate \
  --expected-candidate-digest sha256:REPLACE_WITH_TEST_DIGEST \
  --ordinary-candidate /absolute/path/to/new/c-ordinary/candidate \
  --expected-ordinary-digest sha256:REPLACE_WITH_ORDINARY_DIGEST \
  --command-line-tools /absolute/path/to/locked/command-line-tools \
  --java-home /absolute/path/to/locked/jbr/Contents/Home \
  --target ASSIGNED_TARGET --target-kind emulator \
  --community-debug-signing --allow-dirty --scenario suite \
  --output /absolute/path/to/new/c09-receipt-evidence
```

Replace the example placeholders. The fresh output must not overlap source,
candidate or tool inputs. `--build-only` compiles without device operations and
records execution as not run. `--scenario` may select `normal`, `callback-throws`,
`callback-promise`, `callback-thenable`, `callback-code-getter`,
`callback-throw-undefined`, `callback-throw-proxy`, `regressions` or the combined
`suite`.
The fixed independent review selector is `c09-receipt-window`; consumers cannot
supply a replacement review file. The ordinary/test pair must pass that source
review and build binding before compilation, with no test API in the ordinary
public SDK. SDK/HAR/native bytes, source archives, tool inventories, target,
nonce/PID, complete observations and cleanup commands are retained.

The new ordinary candidate also needs its own real baseline; a prior candidate's
run is not transferable. Run `harness/c09_receipt_window_ordinary.py` with the
same explicit route, paired candidate/digest, tool, target and fresh-output
arguments, omitting `--scenario`. It reuses the existing independent ordinary
consumer/oracle and records compilation, execution and device recovery separately.

The unchanged Lab regression consumers cover these affected paths:

- C/C++/Rust: `full-waiters`, `failed-close-before-guard`,
  `failed-close-after-accepted`, `settling-reentry`, and real `worker-env-exit`.
- Kotlin: `kotlin-live-threads`, `kotlin-settling-reentry`,
  `kotlin-fault-before-guard` and `kotlin-fault-after-accepted`. Its approved
  main-env-only profile does not claim Worker-env cleanup.

The existing `com.madb.c07probe` bundle is used only under exclusive target
ownership and an empty-PID check before installation/start. Every completed run
stops and uninstalls its own probe, with explicit target success responses. No
shared HDC server or other bundle is stopped. Missing or failed observations stay
failed; subprocess termination cannot supply native cleanup evidence. This is a
named C09 slice on the selected candidate and target, not full C07/C09
certification, other-platform evidence, packaging approval or publication.
