# Live workflow status

Pages remains the durable, ten-minute HTML archive. For long builds, attach the
read-only live observer with `scripts/publish-live-status.py`. It publishes an
allowlisted observation every 60 seconds to the dedicated `status-live` branch;
the page checks it every 30 seconds without triggering a Pages build. GitHub/CDN
latency can add delay. The page warns after three minutes without an observation
and on fetch failures. Neither refreshing a page nor publishing a heartbeat
means a theorem has advanced or passed verification.

The observer reads the saved DAG, process identity, dependency readiness/failure
markers, build job counts, and worker log modification times. It never publishes
raw logs, prompts, local paths, or credentials. A PID's start time is checked to
avoid mistaking a recycled PID for the controller. When the controller exits,
the observer publishes a final stopped/finished observation and exits.

Run with the same Python environment as the workflow:

```sh
python scripts/publish-live-status.py \
  --project /path/to/problem-repo \
  --run-dir /path/to/problem-repo/.humanize/github-theorem-prover/runs/RUN \
  --controller-pid CONTROLLER_PID --build-pid BUILD_PID \
  --build-log /path/to/build.log \
  --ready-file /path/to/lean-ready --failed-file /path/to/lean-build-failed
```

Use actual process IDs and the canonical build markers, not estimates. A lock
prevents duplicate observers for one run. Existing runs can be upgraded by
deploying the new `site.js`/`site.css` assets; the workers need not restart.

The data branch is separate from proof branches and Pages. Publication uses a
temporary Git index, preserves other runs, retries fast-forward races, and
refuses a branch without its ownership marker. The checked-out branch, proof
files, and Git index are not changed. Failed publication leaves the last public
observation available, with its original timestamp, for stale-feed detection.

Build percentage is displayed separately from proof completion. Theorem states
and verification/PR counts come only from saved workflow records. Search, filters,
expanded statements, and scroll position survive live updates.
