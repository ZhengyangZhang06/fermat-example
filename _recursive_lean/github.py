"""Bounded GitHub publication through the user's authenticated GitHub CLI."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class PublicationError(RuntimeError):
    """An infrastructure failure; it must not trigger another mathematical proof."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def repository_from_url(url: str) -> str:
    """Accept credential-free GitHub HTTPS and Git SSH remote coordinates."""
    match = re.fullmatch(r"git@github\.com:([^\s]+)", url)
    if match:
        path = match.group(1)
    else:
        parsed = urlsplit(url)
        if (
            parsed.hostname != "github.com"
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port
            or not (
                (parsed.scheme == "https" and parsed.username is None)
                or (parsed.scheme == "ssh" and parsed.username == "git")
            )
        ):
            raise PublicationError(
                "publication requires a credential-free github.com remote"
            )
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise PublicationError("GitHub remote must identify one owner/repository")
    return path


class GitHubClient:
    """Find by durable marker before create, including after an uncertain response."""

    def __init__(self, repository: str, cwd: Path, timeout: float) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise PublicationError("expected a GitHub owner/repository")
        self.repository = repository
        self.cwd = cwd
        self.timeout = timeout

    def request(
        self,
        method: str,
        resource: str,
        payload: dict[str, Any] | None = None,
        *,
        paginate: bool = False,
    ) -> Any:
        command = [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "--method",
            method,
            f"repos/{self.repository}/{resource}".rstrip("/"),
        ]
        if paginate:
            command += ["--paginate", "--slurp"]
        if payload is not None:
            command += ["--input", "-"]
        try:
            result = subprocess.run(
                command,
                cwd=self.cwd,
                input=json.dumps(payload) if payload is not None else None,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PublicationError(
                "GitHub CLI unavailable or timed out; restore access and resume this run"
            ) from error
        if result.returncode:
            status = re.search(r"\(HTTP (\d{3})\)", result.stderr or "")
            # Do not echo transport output: it may contain credential-helper diagnostics.
            raise PublicationError(
                f"GitHub {method} {resource.split('?')[0]} failed; "
                "check gh authentication/repository access, then resume",
                status_code=int(status.group(1)) if status else None,
            )
        try:
            value = json.loads(result.stdout)
            return [item for page in value for item in page] if paginate else value
        except (ValueError, TypeError) as error:
            raise PublicationError(
                "GitHub returned an invalid JSON response"
            ) from error

    @staticmethod
    def _marked(items: list[dict[str, Any]], marker: str) -> dict[str, Any] | None:
        matches = [
            one for one in items if (one.get("body") or "").splitlines()[:1] == [marker]
        ]
        if len(matches) > 1:
            raise PublicationError(
                "multiple GitHub records have the same theorem identity"
            )
        return matches[0] if matches else None

    def issue(self, marker: str, title: str, body: str) -> dict[str, Any]:
        if len(marker + "\n\n" + body) > 65536:
            raise PublicationError(
                "complete theorem issue exceeds GitHub's body limit; shorten the proof "
                "or split the theorem before publishing (proof text is never truncated)"
            )
        items = self.request("GET", "issues?state=all&per_page=100", paginate=True)
        found = self._marked(
            [one for one in items if "pull_request" not in one], marker
        )
        payload = {"title": title, "body": marker + "\n\n" + body}
        if found:
            if found["title"] == title and found.get("body") == payload["body"]:
                return found
            return self.request("PATCH", f"issues/{found['number']}", payload)
        # A failed/uncertain POST escapes. Resume will list server state before any retry.
        return self.request("POST", "issues", payload)

    def find_pull_request(self, marker: str) -> dict[str, Any] | None:
        return self._marked(self.request("GET", "pulls?state=all&per_page=100", paginate=True), marker)

    def merge_verified(self, record: dict[str, Any], *, commit: str, base_commit: str) -> dict[str, Any]:
        """Normal GitHub merge with a head-SHA guard; never bypass protection."""
        current = self.request("GET", f"pulls/{record['number']}")
        if current["head"]["sha"] != commit or current["base"]["ref"] != record["base"]["ref"]:
            raise PublicationError("theorem PR changed after verification; refusing merge")
        if current.get("merged_at"):
            return current
        if current["state"] != "open" or current.get("draft") or current["base"]["sha"] != base_commit:
            raise PublicationError("theorem PR is draft, closed, or has an unverified base; refusing merge")
        result = self.request("PUT", f"pulls/{record['number']}/merge", {"sha": commit, "merge_method": "merge"})
        if not result.get("merged"):
            raise PublicationError("GitHub did not confirm the verified theorem merge")
        merged = self.request("GET", f"pulls/{record['number']}")
        if not merged.get("merged_at") or merged.get("merge_commit_sha") != result.get("sha"):
            raise PublicationError("theorem merge needs remote reconciliation")
        return merged

    def close_proved_issue(self, url: str, marker: str) -> dict[str, Any]:
        prefix = f"https://github.com/{self.repository}/issues/"
        if not url.startswith(prefix) or not url[len(prefix):].isdigit():
            raise PublicationError("invalid theorem issue identity")
        resource = f"issues/{url[len(prefix):]}"
        issue = self.request("GET", resource)
        if "pull_request" in issue or (issue.get("body") or "").splitlines()[:1] != [marker]:
            raise PublicationError("theorem issue identity changed; refusing closure")
        if issue.get("state") == "closed":
            return issue
        return self.request("PATCH", resource, {"state": "closed", "state_reason": "completed"})

    def pull_request(
        self,
        marker: str,
        title: str,
        body: str,
        *,
        head: str,
        base: str,
        commit: str,
    ) -> dict[str, Any]:
        items = self.request("GET", "pulls?state=all&per_page=100", paginate=True)
        found = self._marked(items, marker)
        payload = {"title": title, "body": marker + "\n\n" + body}
        if found:
            if (
                found["head"]["ref"] != head
                or found["base"]["ref"] != base
                or found["head"]["sha"] != commit
            ):
                raise PublicationError(
                    "existing theorem PR has different branch or commit coordinates"
                )
            if found["state"] != "open":
                if not found.get("merged_at"):
                    raise PublicationError(
                        "theorem PR was closed without merge; resolve it before resuming"
                    )
                # Generated descriptions may need a lifecycle-policy update after
                # explicit user authorization changes, without touching proof code.
                if found["title"] == title and found.get("body") == payload["body"]:
                    return found
                return self.request("PATCH", f"pulls/{found['number']}", payload)
            if found["title"] == title and found.get("body") == payload["body"]:
                return found
            return self.request("PATCH", f"pulls/{found['number']}", payload)
        return self.request("POST", "pulls", {**payload, "head": head, "base": base})
