#!/usr/bin/env python3
"""Attach live reporting to a running proof without restarting its workers."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _recursive_lean.live_status import (
    LiveBranch,
    build_observation,
    live_snapshot,
    process_identity,
)
from _recursive_lean.store import atomic_text, now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--controller-pid", type=int, required=True)
    parser.add_argument("--build-pid", type=int, required=True)
    parser.add_argument("--build-log", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--failed-file", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 30:
        parser.error("publication interval must be at least 30 seconds")
    # One publisher per run. Preserve the lock for the process lifetime.
    with (args.run_dir / "live-status.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        seeds = list((args.run_dir / "website/theorem-status").glob("*/*/status.json"))
        if len(seeds) != 1:
            raise RuntimeError(
                "expected exactly one existing status website for this run"
            )
        seed = json.loads(seeds[0].read_text())
        path = str(seeds[0].parent.relative_to(args.run_dir / "website"))
        controller = process_identity(args.controller_pid)
        builder = process_identity(args.build_pid)
        branch = LiveBranch(args.project)
        while True:
            alive = bool(
                controller and process_identity(args.controller_pid) == controller
            )
            try:
                dag = json.loads((args.run_dir / "dag.json").read_text())
                build = build_observation(
                    args.build_log,
                    running=bool(
                        builder and process_identity(args.build_pid) == builder
                    ),
                    ready=args.ready_file.exists(),
                    failed=args.failed_file.exists(),
                )
                payload = live_snapshot(
                    seed, dag, args.run_dir, controller_running=alive, build=build
                )
                commit = branch.publish(path, payload)
                atomic_text(
                    args.run_dir / "live-status.json",
                    json.dumps(
                        {
                            "observed_at": now(),
                            "commit": commit,
                            "branch": branch.branch,
                            "last_error": "",
                        }
                    )
                    + "\n",
                )
                print(
                    f"{now()} published {commit[:12]}: {build['state']} {build['completed']}/{build['total']}",
                    flush=True,
                )
                if args.once or not alive:
                    return
            except Exception as error:
                # Do not publish raw command diagnostics, paths, or credentials.
                print(
                    f"{now()} live publication failed ({type(error).__name__}); retrying",
                    flush=True,
                )
                atomic_text(
                    args.run_dir / "live-status.json",
                    json.dumps(
                        {"checked_at": now(), "last_error": type(error).__name__}
                    )
                    + "\n",
                )
                if args.once:
                    raise
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
