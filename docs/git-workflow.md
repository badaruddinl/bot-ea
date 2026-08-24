# Git workflow

`main` is the repository's only source of truth.

## Start work

1. Fetch and prune `origin`.
2. Record the exact `origin/main` SHA and verify a clean worktree.
3. Create `feature/<concern>` for new capability or `hotfix/<concern>` for a
   correction to behavior already on main.

Do not start new work from another feature/hotfix branch and do not deploy an
unmerged branch as the canonical release.

## Finish work

1. Run focused tests, profile tests, cross-profile isolation, full regression,
   and required MetaEditor/Strategy Tester gates.
2. Push the branch and open a pull request targeting `main`.
3. Merge with a merge commit only after required checks pass.
4. Delete the remote branch after merge and fetch/prune locally.
5. Build or deploy from the resulting main SHA. Preserve a verified rollback
   binary before replacing an installed EA.

Direct pushes, force-pushes, rebases of audited commits, and releases whose
source cannot be resolved to main are prohibited.
