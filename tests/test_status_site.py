from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import test_github_workflow as fixtures
from test_github_workflow import MemoryGitHub, git

from _recursive_lean.github import GitHubClient, PublicationError
from _recursive_lean.runtime import Runtime
from _recursive_lean.status_publisher import StatusPublisher
from _recursive_lean.status_site import StatusWebsite, anchor, public_snapshot, render_dag, render_page


class PagesAPI(MemoryGitHub):
    def __init__(self, cwd, bare):
        super().__init__(cwd, bare)
        self.pages = None
        self.pages_error = None
        self.pages_creations = 0

    def request(self, method, resource, payload=None, *, paginate=False):
        if resource == "pages":
            if self.pages_error is not None:
                raise self.pages_error
            if method == "GET":
                if self.pages is None:
                    raise PublicationError("Pages not configured", status_code=404)
                return self.pages
            self.pages_creations += 1
            self.pages = {
                **payload,
                "html_url": "https://example.github.io/proofs/",
                "status": "building",
            }
            return self.pages
        return super().request(method, resource, payload, paginate=paginate)


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attributes = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


class StatusRenderingTests(unittest.TestCase):
    def test_dag_renders_shared_prerequisites_once_and_orients_edges(self):
        data = self.snapshot([
            {"id": "root", "children": ["scalar", "trace", "kernel"]},
            {"id": "scalar", "status": "proved"},
            {"id": "trace", "depends_on": ["scalar"], "status": "rlcr-lean"},
            {"id": "kernel", "status": "proved"},
            {"id": "obsolete", "status": "proved"},
        ])
        graph = render_dag(data)
        self.assertEqual(graph.count('class="dag-node '), 4)
        self.assertEqual(graph.count('class="dag-edge"'), 4)
        self.assertIn(f'data-from="{anchor("scalar")}" data-to="{anchor("trace")}"', graph)
        self.assertIn(f'href="#{anchor("root")}"', graph)
        self.assertNotIn(anchor("obsolete"), graph)
        self.assertIn("lemmas actually used", graph)

    def test_dag_handles_empty_and_invalid_graph_without_recursing(self):
        self.assertIn("first theorem", render_dag(self.snapshot([])))
        for nodes in ([{"id": "root", "depends_on": ["root"]}],
                      [{"id": "root", "children": ["missing"]}]):
            self.assertIn("graph unavailable", render_dag(self.snapshot(nodes)))

    def snapshot(self, nodes):
        return public_snapshot(
            {
                "nodes": nodes,
                "task": "private prompt",
                "reference_manifest": "/private/path",
            },
            problem="Test problem",
            run="run-1",
            repository="example/proofs",
            statement="True",
            lifecycle="running",
        )

    def test_counts_exclude_obsolete_nodes_and_distinguish_integration_from_acceptance(
        self,
    ):
        data = self.snapshot(
            [
                {"id": "root", "status": "rlcr-lean", "children": ["root.child"]},
                {
                    "id": "root.child",
                    "status": "integrating",
                    "candidate_commit": "abc",
                },
                {"id": "root.obsolete", "status": "proved"},
            ]
        )
        self.assertEqual((data["total"], data["verified"], data["accepted"]), (2, 0, 1))
        self.assertEqual(data["phase"], "In progress")
        self.assertFalse(
            next(one for one in data["nodes"] if one["id"] == "root.obsolete")["active"]
        )

    def test_incomplete_or_cyclic_graph_never_reports_verified(self):
        for nodes in (
            [{"id": "root", "status": "proved", "children": ["missing"]}],
            [{"id": "root", "status": "proved", "depends_on": ["root"]}],
        ):
            with self.subTest(nodes=nodes):
                data = self.snapshot(nodes)
                self.assertFalse(data["graph_ok"])
                self.assertEqual(data["phase"], "Needs attention")

    def test_html_escapes_proof_text_and_never_activates_unsafe_links(self):
        attack = '<img src=x onerror="alert(1)"></script><script>alert(2)</script>'
        data = self.snapshot(
            [
                {
                    "id": "root",
                    "title": attack,
                    "lean_statement": attack,
                    "github_issue_url": "javascript:alert(3)",
                    "github_pr_url": "https://github.com/example/proofs/pull/1",
                    "worktree": "/private/worktree",
                    "message": "sensitive process diagnostics",
                }
            ]
        )
        document = render_page(data)
        parser = Tags()
        parser.feed(document)
        self.assertNotIn("img", parser.tags)
        self.assertEqual(parser.tags.count("script"), 1)
        self.assertFalse(any(name.startswith("on") for name, _ in parser.attributes))
        self.assertNotIn("javascript:", document)
        self.assertIn("&lt;img", document)
        self.assertIn("https://github.com/example/proofs/pull/1", document)
        exposed = json.dumps(data)
        for secret in (
            "private prompt",
            "/private/path",
            "/private/worktree",
            "sensitive process diagnostics",
        ):
            self.assertNotIn(secret, exposed)

    def test_empty_run_and_proved_root_have_distinct_truthful_states(self):
        self.assertEqual(self.snapshot([])["phase"], "Preparing")
        data = self.snapshot([{"id": "root", "status": "proved"}])
        self.assertEqual(data["phase"], "Verified")
        self.assertEqual(data["pull_requests"], 0)
        self.assertIn("not checked", render_page(data))

    def test_local_site_is_self_contained_and_catalog_links_resolve(self):
        with tempfile.TemporaryDirectory() as directory:
            website = StatusWebsite(
                Path(directory),
                problem="Problem A",
                run="run-1",
                repository="example/proofs",
                statement="True",
            )
            website.render({"nodes": []})
            parser = Tags()
            parser.feed(website.entry.read_text())
            for name, value in parser.attributes:
                if (
                    name in {"src", "href"}
                    and value
                    and not value.startswith(("https:", "#"))
                ):
                    self.assertTrue(
                        (website.entry.parent / value).resolve().is_file(), value
                    )
            self.assertTrue((Path(directory) / "theorem-status/index.html").is_file())


class StatusPublishingTests(unittest.TestCase):
    setUp = fixtures.GitHubRuntimeTests.setUp
    new_runtime = fixtures.GitHubRuntimeTests.new_runtime
    node = fixtures.GitHubRuntimeTests.node
    accept = fixtures.GitHubRuntimeTests.accept

    def publisher(self):
        api = PagesAPI(self.project, self.bare)
        self.runtime.github = api
        return StatusPublisher(self.runtime), api

    def test_dag_updates_refresh_local_html_immediately(self):
        record = self.node("root")
        self.runtime.store.update(record.id, "comparing", "local path /private/log")
        document = self.runtime.website.entry.read_text()
        self.assertIn("comparing", document)
        self.assertNotIn("/private/log", document)

    def test_initial_publication_contains_only_status_files_and_enables_pages(self):
        self.node("root")
        publisher, api = self.publisher()
        self.assertTrue(publisher.tick())
        commit = git(self.bare, "rev-parse", "gh-pages")
        names = git(self.bare, "ls-tree", "-r", "--name-only", commit).splitlines()
        self.assertFalse(any(name.endswith(".lean") for name in names))
        self.assertIn(self.runtime.website.path + "/index.html", names)
        self.assertEqual(git(self.bare, "rev-parse", "main"), self.base)
        self.assertEqual(git(self.project, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.project, "status", "--porcelain"), "")
        self.assertEqual(api.pages_creations, 1)
        self.assertEqual(api.pages["source"], {"branch": "gh-pages", "path": "/"})
        self.assertIn(
            self.runtime.website.url,
            self.runtime._issue_body(self.runtime.store.nodes["root"]),
        )

    def test_new_problem_preserves_previous_problem_and_catalog(self):
        first = self.runtime.website
        publisher, api = self.publisher()
        publisher.publish()
        self.runtime.website = StatusWebsite(
            self.runtime.run_root / "second-site",
            problem="Second problem",
            run="second-run",
            repository="example/proofs",
            statement="False → False",
        )
        self.runtime.website.render({"nodes": []})
        StatusPublisher(self.runtime).publish()
        names = git(self.bare, "ls-tree", "-r", "--name-only", "gh-pages")
        self.assertIn(first.path + "/index.html", names)
        self.assertIn(self.runtime.website.path + "/index.html", names)
        catalog = git(self.bare, "show", "gh-pages:theorem-status/index.html")
        self.assertIn("Second problem", catalog)
        self.assertIn(first.problem, catalog)
        self.assertEqual(api.pages_creations, 1)

    def test_existing_homepage_and_custom_domain_are_preserved(self):
        publisher, api = self.publisher()
        existing = publisher._commit(
            "", {"index.html": "Existing homepage", "CNAME": "proofs.example.org"}
        )
        git(self.project, "push", "origin", f"{existing}:refs/heads/gh-pages")
        api.pages = {
            "html_url": "https://proofs.example.org/",
            "source": {"branch": "gh-pages", "path": "/"},
        }
        publisher.publish()
        self.assertEqual(
            git(self.bare, "show", "gh-pages:index.html"), "Existing homepage"
        )
        self.assertEqual(git(self.bare, "show", "gh-pages:CNAME"), "proofs.example.org")
        self.assertTrue(
            self.runtime.website.url.startswith(
                "https://proofs.example.org/theorem-status/"
            )
        )
        self.assertNotIn(
            ".nojekyll",
            git(self.bare, "ls-tree", "--name-only", "gh-pages").splitlines(),
        )

    def test_push_race_retries_on_top_of_other_publishers_commit(self):
        publisher, _ = self.publisher()
        original = self.runtime._workspace_git
        competed = False

        def transport(args, **kwargs):
            nonlocal competed
            if args[0] == "push" and not competed:
                competed = True
                competitor = publisher._commit("", {"competitor.txt": "preserve me"})
                git(self.project, "push", "origin", f"{competitor}:refs/heads/gh-pages")
            return original(args, **kwargs)

        with patch.object(self.runtime, "_workspace_git", side_effect=transport):
            publisher.publish()
        self.assertEqual(
            git(self.bare, "show", "gh-pages:competitor.txt"), "preserve me"
        )
        self.assertIn(
            self.runtime.website.path,
            git(self.bare, "ls-tree", "-r", "--name-only", "gh-pages"),
        )

    def test_pages_source_mismatch_does_not_change_settings_or_proof_state(self):
        root = self.node("root")
        self.accept(root)
        publisher, api = self.publisher()
        api.pages = {
            "html_url": "https://example.github.io/proofs/",
            "source": {"branch": "main", "path": "/docs"},
        }
        self.assertFalse(publisher.tick())
        self.assertEqual(root.status, "proved")
        self.assertIsNone(self.runtime._publication_abort)
        self.assertEqual(api.pages["source"]["branch"], "main")
        self.assertEqual(api.pages_creations, 0)
        self.assertEqual(git(self.bare, "branch", "--list", "gh-pages"), "")
        self.assertTrue(self.runtime.website.entry.is_file())

    def test_authentication_failure_is_not_treated_as_missing_pages(self):
        publisher, api = self.publisher()
        api.pages_error = PublicationError("permission denied", status_code=403)
        self.assertFalse(publisher.tick())
        self.assertEqual(api.pages_creations, 0)
        self.assertIsNone(self.runtime._publication_abort)
        api.pages_error = None
        self.assertTrue(publisher.tick())

    def test_pr_merge_status_does_not_imply_a_proved_theorem(self):
        root = self.node("root")
        publisher, api = self.publisher()
        root.github_pr_url = "https://github.com/example/proofs/pull/1"
        api.prs.append(
            {
                "html_url": root.github_pr_url,
                "state": "closed",
                "merged_at": "2026-10-05T00:00:00Z",
            }
        )
        self.assertTrue(publisher.tick())
        data = json.loads(
            (self.runtime.website.entry.parent / "status.json").read_text()
        )
        self.assertEqual(data["nodes"][0]["pr_state"], "merged")
        self.assertTrue(data["nodes"][0]["pr_checked_at"])
        self.assertEqual(data["verified"], 0)

    def test_status_and_solution_target_cannot_share_a_branch(self):
        with self.assertRaises(ValueError):
            type(self.config)(
                **dict(self.config.model_dump(), github_status_branch="main")
            )

    def test_finished_run_publishes_final_status_and_links_website_from_pr(self):
        _, api = self.publisher()
        with (
            patch(
                "_recursive_lean.github_runtime.repository_from_url",
                return_value="example/proofs",
            ),
            patch.object(
                Runtime, "execute", side_effect=lambda: self.accept(self.node("root"))
            ),
        ):
            self.runtime.execute()
        self.assertFalse(self.runtime._status_publisher._thread.is_alive())
        status = json.loads(
            git(self.bare, "show", f"gh-pages:{self.runtime.website.path}/status.json")
        )
        self.assertEqual(status["lifecycle"], "finished")
        self.assertEqual(status["phase"], "Verified")
        self.assertIn(self.runtime.website.url, api.prs[0]["body"])

    def test_interrupted_run_publishes_paused_status_and_stops_publisher(self):
        self.publisher()
        with (
            patch(
                "_recursive_lean.github_runtime.repository_from_url",
                return_value="example/proofs",
            ),
            patch.object(Runtime, "execute", side_effect=RuntimeError("stopped")),
        ):
            with self.assertRaises(RuntimeError):
                self.runtime.execute()
        self.assertFalse(self.runtime._status_publisher._thread.is_alive())
        status = json.loads(
            git(self.bare, "show", f"gh-pages:{self.runtime.website.path}/status.json")
        )
        self.assertEqual(status["lifecycle"], "paused")

    def test_local_only_mode_keeps_website_without_any_hosting_writes(self):
        self.publisher()
        self.runtime.config = self.config.model_copy(
            update={"github_status_publish": False}
        )
        with (
            patch(
                "_recursive_lean.github_runtime.repository_from_url",
                return_value="example/proofs",
            ),
            patch.object(Runtime, "execute", return_value=None),
            patch.object(StatusPublisher, "publish") as publish,
        ):
            self.runtime.execute()
        publish.assert_not_called()
        self.assertTrue(self.runtime.website.entry.is_file())

    def test_github_http_status_is_preserved_without_leaking_diagnostics(self):
        api = GitHubClient("example/proofs", self.project, 30)
        result = subprocess.CompletedProcess(
            [], 1, "{}", "gh: Not Found (HTTP 404) secret-diagnostic"
        )
        with patch("subprocess.run", return_value=result):
            with self.assertRaises(PublicationError) as raised:
                api.request("GET", "pages")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertNotIn("secret-diagnostic", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
