"""Optional browser regression: run with Playwright installed and Chromium cached."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from _recursive_lean.live_status import live_snapshot
from _recursive_lean.status_site import public_snapshot, render_page

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipIf(
    sync_playwright is None, "optional Playwright dependency is not installed"
)
class LiveBrowserTests(unittest.TestCase):
    def test_live_refresh_preserves_reading_state_and_reports_outage(self):
        seed = {
            "problem": "P",
            "run": "run-one",
            "repository": "owner/repo",
            "statement": "True",
        }
        dag = {
            "updated_at": "2020-01-01T00:00:00Z",
            "nodes": [
                {"id": "root", "title": "Root theorem", "status": "rlcr-lean", "children": ["leaf"]},
                {"id": "leaf", "title": "Prerequisite", "status": "comparing"},
            ],
        }
        build = {
            "state": "Building",
            "completed": 40,
            "total": 100,
            "latest_module": "Mathlib.Test",
            "last_activity": "2026-01-01T00:00:00Z",
        }
        assets = Path(__file__).resolve().parents[1] / "_recursive_lean/status_assets"
        with (
            tempfile.TemporaryDirectory() as directory,
            sync_playwright() as playwright,
        ):
            feed = live_snapshot(
                seed, dag, Path(directory), controller_running=True, build=build
            )
            page_html = render_page(public_snapshot(dag, **seed, lifecycle="running"))
            # Exercise compatibility with the running controller's older HTML.
            page_html = page_html.replace(
                ' data-repository="owner/repo" data-run="run-one"', ""
            )
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1100, "height": 850})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route(
                "https://owner.github.io/**",
                lambda route: route.fulfill(
                    body=(assets / route.request.url.rsplit("/", 1)[-1]).read_text()
                    if route.request.url.endswith(("site.js", "site.css"))
                    else page_html,
                    content_type="text/javascript"
                    if route.request.url.endswith(".js")
                    else "text/css"
                    if route.request.url.endswith(".css")
                    else "text/html",
                ),
            )
            offline = False
            cached_canonical = json.dumps(feed)

            def serve(route):
                if offline:
                    route.abort()
                else:
                    route.fulfill(
                        # Model GitHub's stale canonical cache. Only minute-path
                        # observations advance, even when both requests succeed.
                        body=json.dumps(feed)
                        if "/ticks/" in route.request.url
                        else cached_canonical,
                        content_type="application/json",
                        headers={"Access-Control-Allow-Origin": "*"},
                    )

            page.route("https://raw.githubusercontent.com/**", serve)
            page.goto("https://owner.github.io/repo/theorem-status/problem/run-one/")
            page.wait_for_selector(".live-activity")
            page.locator(".build-details summary").click()
            self.assertIn("40 / 100", page.locator(".live-activity").inner_text())
            self.assertEqual(page.locator(".dag-node").count(), 2)
            self.assertEqual(page.locator(".dag-edge").count(), 1)
            page.locator('.dag-node').first.click()
            self.assertTrue(page.locator("tbody details").first.evaluate("element => element.open"))
            page.locator('[data-zoom="in"]').click()
            self.assertEqual(page.locator(".dag-svg").evaluate("element => element.style.width"), "125%")
            page.locator("#search").fill("Root")
            build["completed"] = 65
            dag["nodes"][1]["status"] = "proved"
            feed = live_snapshot(
                seed, dag, Path(directory), controller_running=True, build=build
            )
            feed["snapshot"]["updated_at"] = (
                dt.datetime.now(dt.UTC) + dt.timedelta(seconds=2)
            ).isoformat()
            page.evaluate("poll()")
            self.assertIn("65 / 100", page.locator(".live-activity").inner_text())
            self.assertEqual(page.locator(".dag-node.verified").count(), 1)
            self.assertEqual(page.locator(".dag-svg").evaluate("element => element.style.width"), "125%")
            self.assertEqual(page.locator("#search").input_value(), "Root")
            self.assertTrue(
                page.locator("tbody details").first.evaluate("element => element.open")
            )
            self.assertEqual(
                page.locator(".metrics strong").first.inner_text(), "1 / 2"
            )
            offline = True
            page.evaluate("poll()")
            self.assertIn("Live feed unavailable", page.locator("#stale").inner_text())
            self.assertFalse(page.locator("#stale").is_hidden())
            self.assertIn("65 / 100", page.locator(".live-activity").inner_text())
            page.evaluate(
                'fetchFailed = false; lastObservation = "2000-01-01T00:00:00Z"; showFreshness()'
            )
            self.assertIn("Status feed is stale", page.locator("#stale").inner_text())
            offline = False
            page.evaluate("poll()")
            self.assertTrue(page.locator("#stale").is_hidden())
            page.set_viewport_size({"width": 390, "height": 844})
            self.assertTrue(
                page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            )
            self.assertEqual(errors, [])
            browser.close()


if __name__ == "__main__":
    unittest.main()
