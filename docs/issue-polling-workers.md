# Autonomous theorem issue workers

`github-theorem-prover` defaults to eight long-lived, same-host pull workers.
Each independently polls GitHub's open issue list, checks the frozen run marker,
active theorem graph, immutable workspace handoff and accepted prerequisites,
then acquires exclusive ownership and starts its own isolated RLCR process.
No parent or other worker sends it a job notification. A decomposition publishes
child issues and Git handoffs, then releases its worker slot. Parents become
eligible again once their prerequisites pass the existing acceptance gates.

```yaml
github_worker_mode: poll
github_issue_workers: 8
github_issue_poll_interval: 30
```

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
