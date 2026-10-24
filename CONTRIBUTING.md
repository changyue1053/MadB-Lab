# Contributing to MadB-Lab

Use an existing work package and document its sub-scope, specification revision, paths and checks in the PR. The [pinned reference](docs/reference/README.md) supplies the local C01 rules. Current task progress remains in MadB's authoritative catalog.

Run `python3 scripts/check.py` with Python 3.14.4. Repository tests verify only C01 independence and specification integrity; future platform changes must run the actual consumer against an identified public candidate. Provide independent expected values and describe missing evidence honestly.

Read-only specification snapshots are refreshed from a reviewed MadB commit, with links pinned and checksums updated together. Do not alter their rules to accommodate an implementation deviation.

Only contribute content you can license under Apache-2.0 and retain third-party notices. Use SECURITY.md for vulnerability reporting.

## Main branch merge controls

The repository owner authorized public visibility on 2026-10-24. The effective `main` protection requires the `MadB-Lab C01 baseline` check and an up-to-date PR branch, applies to administrators, and prohibits force pushes and branch deletion. The required check is associated with GitHub Actions. A workflow file alone is not proof that these controls are active.

The reproducible request is stored in `.github/branch-protection.json`. An authorized maintainer can apply it with `gh api --method PUT repos/changyue1053/MadB-Lab/branches/main/protection --input .github/branch-protection.json`. Read back the effective settings and validate that a failing required check blocks merging after changing repository visibility, permissions or merge controls. Do not weaken the required checks to resolve a configuration failure.

C01 verification is recorded in the [MadB review](https://github.com/changyue1053/MadB/blob/codex/c01-baseline/docs/reviews/2026-10-24-c01-public-repositories.md). Repository visibility does not imply a software release or platform certification; the current task catalog and the PR's actual checks remain the acceptance evidence.
