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
                return found
            if found["title"] == title and found.get("body") == payload["body"]:
                return found
            return self.request("PATCH", f"pulls/{found['number']}", payload)
        return self.request("POST", "pulls", {**payload, "head": head, "base": base})
