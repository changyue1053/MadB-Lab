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
local L02 observation report; it neither rewrites old C05 cases/results nor
claims full candidate certification or full L02 acceptance.

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
Until those real new candidates exist, runtime results remain unverified.
