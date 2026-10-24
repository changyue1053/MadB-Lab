# Contributing to MadB-Lab

Use an existing work package and document its sub-scope, specification revision, paths and checks in the PR. The [pinned reference](docs/reference/README.md) supplies the local C01 rules. Current task progress remains in MadB's authoritative catalog.

Run `python3 scripts/check.py` with Python 3.14.4. Repository tests verify only C01 independence and specification integrity; future platform changes must run the actual consumer against an identified public candidate. Provide independent expected values and describe missing evidence honestly.

Read-only specification snapshots are refreshed from a reviewed MadB commit, with links pinned and checksums updated together. Do not alter their rules to accommodate an implementation deviation.

Only contribute content you can license under Apache-2.0 and retain third-party notices. Use SECURITY.md for vulnerability reporting.

## Private repository merge controls

The C01 branch-protection request is stored in `.github/branch-protection.json`. GitHub currently rejects it with HTTP 403 because the selected private repository lacks the required plan capability. This file is prepared configuration, not an active protection rule; C01 remains unaccepted and its draft PR stays unmerged. Do not make the repository public or remove the check requirement to work around it.

After the account has the required capability, the authorized maintainer can apply the request with `gh api --method PUT repos/changyue1053/MadB-Lab/branches/main/protection --input .github/branch-protection.json`, read back the effective configuration, and verify a failing required check blocks merging. Only then may C01's remaining acceptance be assessed.
