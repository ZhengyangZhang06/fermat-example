"""Generate a local status website using clearly labelled demonstration data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _recursive_lean.status_site import StatusWebsite
from _recursive_lean.store import now


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="directory for the generated demo website"
    )
    args = parser.parse_args()
    stamp = now()
    nodes = [
        {
            "id": "root",
            "title": "Main theorem",
            "lean_name": "Submission.main_theorem",
            "status": "waiting-children",
            "children": ["root.bound", "root.limit", "root.final"],
        },
        {
            "id": "root.bound",
            "title": "Establish the uniform bound",
            "lean_name": "Submission.uniform_bound",
            "depth": 1,
            "parent": "root",
            "status": "proved",
        },
        {
            "id": "root.limit",
            "title": "Construct the limiting object",
            "lean_name": "Submission.limit_exists",
            "depth": 1,
            "parent": "root",
            "status": "integrating",
            "candidate_commit": "a" * 40,
            "children": ["root.limit.compact"],
        },
        {
            "id": "root.limit.compact",
            "title": "Prove compactness",
            "lean_name": "Submission.compactness",
            "depth": 2,
            "parent": "root.limit",
            "status": "proved",
        },
        {
            "id": "root.final",
            "title": "Pass the bound to the limit",
            "lean_name": "Submission.limit_bound",
            "depth": 1,
            "parent": "root",
            "status": "waiting-lean",
            "depends_on": ["root.bound", "root.limit"],
        },
    ]
    for node in nodes:
        node.update(
            updated_at=stamp, lean_statement="True /- demonstration statement only -/"
        )
    website = StatusWebsite(
        args.output,
        problem="Example problem · demo data",
        run="demo-run",
        repository="humanfia/math-lean-flow",
        statement="True /- demonstration statement only -/",
    )
    website.lifecycle = "finished"
    website.render({"nodes": nodes, "updated_at": stamp})
    print(website.entry)


if __name__ == "__main__":
    main()
