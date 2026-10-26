# L02 bounded-value public consumers

This Lab slice consumes seven independently pinned public candidates: five
`Reading` author revisions and separate `grow` / `explode` auxiliary authors.
The authoritative accepted ABI is the L02 finite-value decision. The Lab owns
its expected trim bytes, integer errors, Unicode rejection vectors, version
changes and wrong-provider behavior; it imports no producer rules or generators.

`l02_values.c` uses the ordinary generated C entry for business calls. The
`MADB_LAB_AUTHOR=0..4` compile selection is a Lab oracle for the five predefined
author fixtures, not a producer method allowlist. Inputs are normal inline C
model values. Calls do not receive interface/profile hashes, handles or a CLI.
The verifier supplies expected identity to the separate evidence observer only;
the ordinary generated entry obtains its own expected identity from its header.

The real candidate path runs values, invalid-input and raw mechanical-pointer
checks, bootstrap protocol checks and actual header/library mismatches. It
records the loaded bootstrap image, actual identity, process and assertion
completion. Misaligned tests use allocated storage; no invalid arbitrary
address or overlapping output is presented as a safely rejectable pointer.

`MADB_LAB_STUB=1` links the actual public inline header to an independent bad
provider. Its 22 vectors (24 with a fallible method) test bootstrap/raw counts,
identity priority and invalid output protocol. These counters describe only
that helper/provider fixture, never real Rust allocation, author calls or cleanup.
`l02_values_aux.c` separately consumes natural Rust providers returning 65-byte
text or panicking under a catchable unwind configuration. It does not promise
recovery from abort or OOM abort. Input `try_reserve` failure and Rust allocation
cleanup need separate producer-side generated-shim evidence.

The 29 existing-format case instances freeze before compilation/target calls;
seven report/1 documents bind candidate, profile, actual tool identities, Lab
revision, case/catalog digests and raw commands. The five export cases are
static evidence; the deleted API linking case is compiled evidence. Other cases
have target-run evidence, with helper-only scope explicitly retained. No numeric
resource counts are invented for inline values. A failed shared input closure
blocks qualification of all cases; timeouts and missing evidence are errors.

Run `python3 scripts/test_l02_values.py` for evidence-rule checks. It requires the
Lab's pinned Python and does not run or certify an SDK. For formal native runs,
use a clean Lab revision and the actual frozen producer revision:

```text
python3 scripts/verify_l02_values.py --candidates /absolute/candidates \
  --producer-revision FULL_COMMIT --lab-revision FULL_COMMIT \
  --candidate-digest author-0=sha256:... --candidate-digest author-1=sha256:... \
  --candidate-digest author-2=sha256:... --candidate-digest author-3=sha256:... \
  --candidate-digest author-4=sha256:... --candidate-digest aux-grow=sha256:... \
  --candidate-digest aux-panic=sha256:... --output /absolute/new-run-directory
```

The native run supports the actually provisioned macOS arm64 and Linux x86_64
glibc consumer environments only. Compiler images and header dependencies must
match each public toolchain receipt. Linux under QEMU is labeled by its actual
execution environment and supplies no physical-hardware performance claim.
Old engine 7/9 exports and their diagnostic candidates have a separate verifier;
this suite does not recertify those candidates or the full L02 package.
