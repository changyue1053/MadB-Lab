# Contributing to MadB-Lab

Use an existing work package and document its sub-scope, specification revision, paths and checks in the PR. The [pinned reference](docs/reference/README.md) supplies the local C01 rules. Current task progress remains in MadB's authoritative catalog.

Run `python3 scripts/check.py` with Python 3.14.4. Repository tests verify only C01 independence and specification integrity; future platform changes must run the actual consumer against an identified public candidate. Provide independent expected values and describe missing evidence honestly.

Read-only specification snapshots are refreshed from a reviewed MadB commit, with links pinned and checksums updated together. Do not alter their rules to accommodate an implementation deviation.

Only contribute content you can license under Apache-2.0 and retain third-party notices. Use SECURITY.md for vulnerability reporting.
