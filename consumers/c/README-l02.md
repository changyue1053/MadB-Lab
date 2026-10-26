# L02 independent C diagnostics consumer

Task: L02, checked construction and the approved bounded native diagnostics slice.
Authority: the project owner's approved native SDK decision revision 2 and its
L02-N01…N16 vectors; MadB baseline `bc32a61e0dd0fa4f35e57421c309619304b97381`,
Lab baseline `341088a122cb36f468367f49b0f3d45d01d86a24`.

This consumer imports only installed public `madb_rust.h`,
`madb_rust_client.h` and, for explicitly selected companion profiles,
`test-support.h`. It never reads producer implementation files. Its expected
values, event phases, FIFO capacity and resource postconditions are independent
of producer code. The checked constructor takes no caller-supplied identity.

The four profiles are checked separately: default 7, test 14, diagnostics 9,
diagnostics-test 16 native exports. `scripts/verify_l02.py` requires new clean
producer candidates, their fixed digests, a clean Lab revision and a matching
real compiler/host. There is no dirty/provisional acceptance switch. Output is a
local L02 observation report plus two existing `madb.report/1` documents, one per
diagnostics selector. These neither rewrite old C05 cases/results nor claim full
candidate certification or full L02 acceptance.

The real-SDK cases cover checked creation, ordinary bytes/callback/close/release,
diagnostics default-off/on, exact stage and token correlation, FIFO64/drop-new,
disable/re-enable, rejected outputs, concurrent controls/work, and a separate
consumer-owned blocked exporter. Test companions additionally exercise existing
operation/source-lease gates and token exhaustion. Two fresh processes establish
independent loaded-image observations; two filesystem copies alone do not.

Helper stub cases are labeled `stub-only`: they link the actual generated helper
to small independent bootstrap/create definitions to exercise five result kinds,
interface-before-profile precedence, call counts and zero outputs. They do not
prove SDK resource behavior. Actual cross-profile installed-library pairings
also exercise mismatch rejection. Private lock poisoning, record-ID exhaustion
and exact atomic wrap tests remain producer unit-test evidence, not public Lab
claims. Performance reports actual bounded samples without invented thresholds.

Actual mismatch probes retain both default-header pairs and both diagnostics-header
pairs: each header meets the corresponding companion profile and the other ABI's
companion. A mismatch-only consumer omits optional diagnostic function calls, so
the deliberately wrong library reaches bootstrap rather than failing at link.
Public companion counters must remain unchanged. Report case evidence is attached
to the header candidate actually compiled; another header's result cannot satisfy
the diagnostics candidate's checked-constructor case.

Run `python3 -B scripts/test_l02.py` using the Lab pinned Python for local parser
and refusal checks. Run `python3 -B scripts/verify_l02.py --help` for the explicit
four-candidate root, independently pinned digests/revisions and output directory.
Runtime results require those independently pinned clean candidates.

The five independent templates under `cases/l02/` define the existing required
IDs. Before compilation or any target invocation the runner validates their C
fixture bytes, instantiates their exact candidate selectors and actual tool
environment, and writes all five definitions plus `case-inputs.json`. Instance
digests use the existing `madb.case/1` projection; the catalog digest uses the
existing Lab path-and-byte catalog rule. Each target process has a 60-second
watchdog; each case additionally enforces the sum of its declared target-step
budgets. Compilation has its separate 120-second process budget. Each step is a
fresh process; other independent cases may run between a case's ordered steps.

New runs retain `report.json` as their full local observation, and additionally
write `c-to-rust-diagnostics.report.json` (three cases) and
`c-to-rust-diagnostics-test.report.json` (two cases). These standard reports bind
the pre-execution instances, actual input/tool/profile/candidate/Lab/catalog
identities, raw command logs and source archive. Case duration sums actual target
process durations; setup/compile durations remain in the command attachments.
The fixed helper modes, capture states, two fresh instances and both mismatch
providers must all be observed in order for their own header candidate.

A real C assertion failure is `failed`; watchdog expiration, missing evidence,
unexpected process failure or a changed final input is `error`. A failed shared
run/closure prerequisite prevents every case in that run from acquiring a pass;
the owning case records the failure and other case qualifications are `blocked`
with its case ID. No process kill or exit alone establishes SDK cleanup. Actual
confirmed C cleanup assertions remain in raw logs; `resource_observations` stays
empty because this consumer does not emit full numeric resource snapshots.
Preflight failures before valid instances exist produce only the local error
record. Historical local observations are never converted into new standard
passes: the new clean Lab revision must execute the consumer again.

The runner admits the existing native targets `aarch64-apple-darwin` on arm64
macOS and `x86_64-unknown-linux-gnu` on x86_64 glibc Linux. The macOS SDK,
deployment target 14.0, compiler flags and receipt checks retain their original
behavior. Linux uses its candidate-bound Clang and symbol-inspector images,
the exact GNU target and C11 warning flags, and the observed Clang resource
directory. It does not inherit Apple SDK/deployment environment variables.

Linux has two separately recorded dependency closures. A generated Lab probe
includes only the installed public `madb_rust.h` and `madb_rust_client.h`; its
actual Clang `-M` depfile must match every header in the public toolchain receipt.
Resource headers match their resource-relative paths. A `native/<basename>-<sha>`
system-header entry must resolve to exactly one observed `/usr/include` dependency
with the same basename, byte hash and size. Missing, ambiguous, changed, unknown
or extra public-header inputs fail. Only explicitly named Rust `.rlib` entries
remain producer-only receipts; they are not claimed as C-consumer dependencies.
No producer backend file or private source supplies the mapping.

The actual C consumer also includes POSIX headers for threads, dynamic loading,
timing and output. Those additional dependencies need not appear in the producer
header receipt: its own real depfile records every input and checks bytes before
and after the run within the public include, `/usr/include` and observed resource
roots. They are never described as producer-locked SDK inputs. The Linux header
probe source, depfile and complete input inventory are preserved in the local
report and rechecked after target execution. Host-side binding tests and compiler
probes do not establish a Linux SDK pass; all four clean Linux candidates must
still complete the same real processes, exact export checks and five cases.
