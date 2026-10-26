# L05 native and ArkUI development composition

This independent consumer combines an exact frozen C ordinary public C07 HAR
with a separately delivered pair of public L05 development sources. It never
imports a neighboring producer checkout. `Boundary.ets` in the temporary HAP
only re-exports `Engine`, `Snapshot` and `Subscription` from the public HAR;
the two delivered observation sources are copied byte for byte.

The source delivery contains `StateObservation.ets`, `ArkUIStateModel.ets`,
`README.md`, `LICENSE`, `NOTICE` and `source-inputs.json`. The producer's
`tests/integration/l05_arkts_observation/prepare_sources.py` creates this bundle.
Obtain the two source digests and candidate digest independently when freezing
the inputs. The consumer verifies those trusted digests as well as the complete
source inventory; a self-consistent edited inventory cannot authorize changed
observation code. This source delivery is not a published package or a C10
candidate.

Use the pinned Python from `.python-version`. Claim the selected target through
the main coordinator before running. `--output` must be fresh and outside the
Lab, candidate, source and tool directories. The SDK, compiler, JBR and native
closure are checked against the candidate's frozen toolchain identity.

```sh
python3 -B scripts/test_l05.py
python3 -B scripts/verify_l05.py \
  --candidate /absolute/path/to/frozen/c-ordinary/candidate \
  --expected-candidate-digest sha256:<independently-trusted-candidate-digest> \
  --observation-source /absolute/path/to/public-source-delivery \
  --expected-state-sha256 <independently-trusted-state-source-sha256> \
  --expected-ui-sha256 <independently-trusted-ui-source-sha256> \
  --command-line-tools /absolute/path/to/locked/command-line-tools \
  --java-home /absolute/path/to/locked/jbr/Contents/Home \
  --target <assigned-hdc-target> --target-kind emulator \
  --community-debug-signing \
  --output /absolute/path/to/fresh/l05-evidence
```

The angle-bracket entries are values to replace before running. Community debug
signing is explicit and is not production signing; `--signing-config` is the
alternative. The runner installs only `com.madb.l05probe`, refuses to replace an
already running instance, and stops/uninstalls that bundle in cleanup. It does
not stop the shared HDC server or other applications. Cleanup records the target
command output and absence of the test process, and requires explicit successful
stop/uninstall responses.

The report distinguishes four checks:

- Compile: a Release, obfuscated HAP with the frozen HAR's exact native bytes,
  source archive, SDK profile and namecache recorded.
- Native: two independent `StateObservation` instances use the same real Engine;
  duplicate attach is rejected, one stops and drains while the other continues,
  the first reattaches without invented replay, and explicit owner closes finish.
- UI: real `@ComponentV2` pages consume the unmodified `@ObservedV2` model. HDC
  UI hierarchy snapshots and clicks verify visible `EMPTY → UI-1`, page hide,
  a hidden publish with no model change, return with reset `EMPTY`, then visible
  `UI-3`. The hidden page retains its close promise; the application owner stays
  alive. Each assertion requires an exact unique visible UI node. Click bounds
  come from the recorded hierarchy. Nonce/PID-bound logs independently verify
  lifecycle counts and ordinary Engine operations.
- Cleanup: only the test bundle is stopped and uninstalled, with the result
  separate from compile/native/UI outcomes.

Output includes the candidate and source identities, consumed Lab source hashes,
tool inventories before/after, actual target metadata, HAP/source archives,
command logs, layout snapshots and observations. Missing evidence, timeout,
assertion failure or a changed consumed input fails the run.

This slice covers the C ordinary route and actual page hide/return on the
selected target. It does not cover page destruction, process/background/rotation
matrices, Kotlin/other native routes, native close-failure injection or strict
resource counters. The hidden publish occurs after observation close has drained;
it does not force an already queued native late callback to race with close.
An emulator run does not establish physical-device results.
Neither this development report nor the host rejection tests certify C07,
complete all of L05, deliver C10 packaging or authorize publication. Work-package
status remains in MadB's catalog. The host rejection tests must be run explicitly;
they are not part of `scripts/check.py`'s existing discovery directory.
