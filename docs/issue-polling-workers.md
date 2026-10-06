# Autonomous theorem issue workers

`github-theorem-prover` defaults to eight long-lived, same-host pull workers.
Each independently polls GitHub's open issue list, checks the frozen run marker,
active theorem graph, immutable workspace handoff and accepted prerequisites,
then acquires exclusive ownership and starts its own isolated RLCR process.
No parent or other worker sends it a job notification. A decomposition publishes
child issues and Git handoffs, then releases its worker slot. Parents become
eligible again once their prerequisites pass the existing acceptance gates.

An existing candidate rejected by the outer reviewer returns directly to Lean
repair with the retained rejection in its implementation plan. It does not reopen
the accepted mathematical proof or decompose the same theorem again.

```yaml
github_worker_mode: poll
github_issue_workers: 8
github_issue_poll_interval: 30
```

With explicit user authorization, enable `github_auto_merge: true` and
`github_close_proved_issues: true`. After all proof and integration gates pass,
the workflow publishes the solution PR, verifies its exact head and frozen base,
and requests a normal GitHub merge without bypassing branch protection. It checks
that the remote merge tree equals the verified publication tree before closing
the matching theorem issue as completed. Changed heads/bases, failed merges, or
unverified proofs cannot trigger closure. Lost responses are reconciled by reading
GitHub state; already-merged review bases are never reset. Child PRs merge into
their frozen review-base branches; the verified root PR integrates the whole
solution into the configured target branch. Both options default off in other
experiments until authorization is supplied. The dashboard reports issue and PR
states separately from proof acceptance.

The status page includes an accessible SVG dependency DAG with prerequisite-to-
dependent arrows, clickable theorem cards, status colors, related-edge highlighting,
zoom controls, and a compact eight-worker roster. These are workflow prerequisites;
the final proof document identifies actual formal dependencies. Graph zoom, scroll,
expanded details, and search survive live snapshot refreshes.

The eight workers are independent polling threads in one supervisor process;
proof execution uses separate processes/worktrees. They are not eight machines.
Polling intervals have jitter. Only ready issues occupy proof workers; an idle
worker is not an active model session. `dispatch` retains the legacy scheduler.

## Race and restart safety

- A stable OS `flock` per repository/issue provides atomic ownership across
  threads and processes on the same filesystem. Labels and comments are not locks.
- Locks never expire or get deleted: a slow worker cannot lose ownership to a
  timestamp-based takeover. The OS releases them when their owner dies.
- After claiming, each worker rechecks local dependencies and remote issue state.
- Existing store, publication and integration locks serialize shared mutations.
- Successful child-history applications have local Git receipts tied to their
  resulting commit. A retry skips a receipt only when that commit is an ancestor
  of the current worktree, preserving later proof repairs without accidentally
  skipping an overlay on an unrelated branch. Receipts are not proof evidence;
  combined-source verification is still required.
- A durable RLCR receipt records PID plus Linux process start identity. After a
  supervisor restart, the claiming worker adopts the live process, leaving its
  worktree untouched. It does not launch a duplicate. An ambiguous spawn receipt
  fails closed and requires process reconciliation; it is never blindly retried.
- Orphan exit alone is not success. A recorded successful exit or the specific
  run's `complete-state.md` is required, followed by the unchanged exact-contract
  comparator, fresh independent review and solution PR gates.

This is deliberately a **single-host, shared-filesystem** design. Do not deploy
independent copies across hosts: GitHub issue updates are not compare-and-swap
claims. That deployment needs a shared transactional claim service.

The local `issue-workers.json` roster records all eight workers. The live website
exports only worker IDs, state, issue numbers, poll counts and last-poll times;
logs, claim tokens, process IDs and paths remain private. A working worker does
not poll again until its current issue yields or completes.

## Final root proof handoff

The root implementation commits `proofs/github/RUN/root-final-proof.md` with the
actual complete natural-language argument, used dependencies and library reuse
provenance. The initial outline remains historical; a changed formal proof route
must not be published with stale prose or unresolved conditional obligations.
The independent Lean reviewer checks the final prose against the candidate and
records its exact Git blob ID. Root acceptance rejects missing prose, absent
review, or a mismatching blob. The issue and PR then use that reviewed candidate
document, not the old outline. This does not weaken any comparator or axiom gate.

The final combined solution must preserve every accepted child's exact qualified
name and frozen type, including historical child lemmas unused by the root proof.
The Deuring project's comparator exports and checks all retained theorem contracts
together, so a valid root cannot hide a renamed child, changed type or proof hole.
