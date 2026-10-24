# MadB-Lab Agent entry

Read the [pinned method](docs/reference/engineering/07-agent-development.md), [Lab architecture](docs/reference/validation/02-lab-architecture.md), [clean code](docs/reference/engineering/02-clean-code.md) and [quality gates](docs/reference/engineering/05-review-and-quality-gates.md). Source revision and integrity are recorded in [reference metadata](docs/reference/README.md). Current task status is maintained in MadB's catalog, not this snapshot.

Record the existing task ID/sub-scope, specification revision, paths/non-goals and actual checks in the task or PR. C01 establishes repository checks only; cases, candidate format and consumers belong to their existing work packages.

Consume public candidates through their public interfaces. Do not import MadB private crates, neighboring source folders or developer caches. Expected results must be independently defined; do not reuse production rules as the oracle. Keep normal reports, temporary projects and device output out of source commits.

Use Python from .python-version and run `python3 scripts/check.py` from this repository root. It requires only the standard library. Add platform checks with actual consumers; do not invent device results or count C01 checks as SDK certification.

Preserve unrelated work; do not weaken assertions, update expected values solely to remove failures, or edit read-only specification snapshots independently. Report actual changes/checks, missing environments and incomplete acceptance. Publish only within explicit task authorization and applicable publication checks.
