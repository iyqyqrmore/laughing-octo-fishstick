# v92 cleanup inventory — October 31, 2026

Removed remote branches `coincat-v80` and `coincat-v90` after explicit user
cleanup clarification and verifying both tips are ancestors of the current source.
Their commits remain reachable; the saved SHA references below remain valid.
Remote listing confirmed both names absent after deletion. No GitHub repository,
Codex library item, financial data or backup has been deleted. This session exposes Git repository access but no GitHub account
repository-list/deletion API or Codex library listing/deletion tools. Names or links
and supported access are required to identify external deletion targets.

## Current repository remote branches

| Branch | Verified tip | Initial classification |
|---|---|---|
| coincat-eth-farmer-design | e0c9b3596332265fd7a5a51c5309b3d5e95027ce | Preserve: current source |
| coincat-v91 | 752a01096e93e98cc72dc3d9287a338bd55d0c21 | Preserve: baseline |
| coincat-v90.1 | daeff92135fba3d877cf74dcacb3eb6f6ce35ac8 | Preserve recovery reference for retired modules |
| coincat-v90 | b32a539c29bb5b1b9e8ffb61e25c5cc7f5340597 | Removed remote branch; commit preserved in current history |
| coincat-v80 | 014a5ad1a786ce9a01680e3b8daa63c0e6f6f4f1 | Removed remote branch; commit preserved in current history |
| coincat-v70.1 | 014a5ad1a786ce9a01680e3b8daa63c0e6f6f4f1 | Retained: server refuses deletion of its current branch |

These are branches in ONE repository, not six repositories. Matching tips prove
identical committed content, not absence of releases, links or other dependencies.
Deleting duplicate branch names usually saves negligible storage because Git
shares objects. No history rewrite or object deletion is proposed.

## Local space

Before restoration the workspace held approximately 468 KiB and no source files.
After fetching, repository Git objects occupy approximately 2.20 MiB, with no
reported garbage. No older source ZIPs, duplicate checkouts or mounted library
files were found in `/workspace/library-files` or `/workspace/shared/downloads`.
Those empty mounts do not prove the user's Codex library is empty. Runtime
setup/cache files used for verification are not historical release clutter.

## Cleanup procedure once targets are available

- Keep the current source and v91 baseline, private records/backups, and the sole
  copy of any needed diagnostic report.
- Inventory named old repositories and library items, including unique work,
  releases, external references and actual sizes. Do not infer obsolescence from age.
- Prefer removing exact duplicate downloadable archives after verifying a retained
  copy and checksum. Archive repositories when retention is uncertain; archiving
  preserves history but does not reclaim Git storage.
- For a repository deletion, first verify a recoverable backup including relevant
  Git refs and any required releases/LFS assets; a source ZIP alone is insufficient.
- Record concrete deletion targets and preservation evidence before irreversible
  removal. Report actual removed items and measured savings, not estimated savings
  from deleting names or hiding archived repositories.

## Cleanup outcome

All five older tips were verified ancestors of e0c9b35. The first atomic deletion
request made no changes because the server refused deletion of its current branch,
coincat-v70.1. A second atomic request removed v80 and v90 with expected-tip leases.
v70.1 remains blocked by server policy; changing the default/current branch needs
a supported GitHub management interface unavailable here. v90.1 and v91 remain
needed recovery/baseline references. No measurable Git-object storage saving is
claimed: only branch references were removed, with history retained. Codex library
cleanup remains unavailable through this session.
