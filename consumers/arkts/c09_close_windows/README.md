# C09 normal-close admission supplement

Task: C09, normal `Runtime.close()` admission before physical ACK. Inputs are the
existing independently admitted C07 public test candidates and their inventoried
diagnostic contracts. Applicable decisions are ADR-0013 and the current C09
catalog acceptance. This is additional evidence, never a change to a historical
C07 report or whole-package status.

Only the new consumer directory and `harness/c09_close_windows*` are owned here.
The runner reuses Lab candidate admission, tool verification, Release HAP build,
nonce/PID logging and bounded target execution. Expected lifecycle/rejection
values are independently defined in Lab. No producer private source is imported.

C/C++/Rust hold the actual phase2 work before `Work.finish`. Kotlin holds actual
worker exit while the existing cleanup job calls `pthread_join`. Both require
two owner turns with the original close Promise pending, exact typed
`RuntimeAlreadyOpen` (C/C++/Rust) or `AlreadyInitialized` (Kotlin), unchanged actual hold after the rejected call, explicit
release, final original physical/resource/receipt retirement, then actual new
Runtime business work and cleanup. A timeout or recovery force-stop proves none
of these obligations.

The first Kotlin supplement run used the C-route spelling and failed with the
actual typed `AlreadyInitialized`. That failed report is retained. Independent
review of frozen producer `18256fcc4b26cf3cd1e2e79c39b86c2512e012d9`,
`sdk/kotlin/arkts-owned/native/bootstrap.cpp.in:170`, confirms that an occupied
slot has always used this spelling; the frozen public facade preserves the
native code as `BoundaryError`. ADR-0013 requires rejection without unifying
these route error names. The new Kotlin oracle therefore requires only the
exact `AlreadyInitialized`, never any error, and must run in a new output
directory. This correction does not amend the failed run or candidate.

Kotlin runtime counters accumulate across same-process epochs. The first closed
Runtime requires exactly one started/joined engine, the second exactly two;
per-epoch live obligations must still return to zero and every creation/release
pair must match. The initial second-epoch oracle incorrectly reused a
single-Runtime count and its failed report is retained; the fixed check does not
weaken retirement, receipt or thread assertions.

The second window, physical ACK reached but final receipt not yet consumed, has
no deterministic public cut point in these frozen facades. It is recorded as
`unavailable`; this supplement does not test it with timer races, private access,
or inherited prior passing results. Adding a test hook needs a separate decision
and new companion candidate identities; frozen candidates are never patched.

Compile without touching any device:

```sh
python3 harness/c09_close_windows.py --candidate <public-test-candidate> --route c \
  --command-line-tools <pinned-sdk-cli> --java-home <pinned-jdk> \
  --community-debug-signing --build-only --allow-dirty --output <new-empty-dir>
```

To run after the single device owner releases it, omit `--build-only` and add
`--target <explicit-id> --target-kind emulator` (or `physical`). No device
enumeration/server restart occurs. Use explicit signing config instead of
community debug signing where applicable. The output path must not overlap the
Lab/candidate/tool/signing inputs. An existing probe PID rejects execution;
only a start dispatched by this run permits the final recovery stop.
`--allow-dirty` is provisional only;
the source/HAP/namecache/log inventory binds the exact executed input. Compile
results, runtime results and the unavailable second window remain separate in
the local report; it does not introduce a public report format or certification.

The pinned Lab Python runs the independent oracle checks with
`python3 harness/c09_close_windows_tests.py`. Synthetic frames used there are
parser/rejection tests, not target-run evidence. Actual consumer source and
ordinary/test identity must still be checked by the build and target runner.
