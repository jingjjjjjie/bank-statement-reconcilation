"""Dashboard decisions only touch temporary duplicate fixtures in these tests."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tests.http_server import TestServer
from unittest.mock import patch

from dashboard.app import Review, create_app, workflow_guide
from dashboard import development
from reconciliation.duplicate_workflow import organize, check
from reconciliation.token_usage import record


class DashboardTests(unittest.TestCase):
    def setUp(self):
        # Use an isolated source and recovery directory for every test.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "sources"
        self.root.mkdir()
        for name in ("a.txt", "b.txt", "c.txt"):
            (self.root / name).write_text("identical receipt", encoding="utf-8")
        self.manifest = self.base / "manifest.json"
        organize(self.root, self.manifest)
        self.review = Review(self.manifest, self.base / "dashboard-data")
        self.group = next(iter(self.review.groups))
        self.ids = self.review.groups[self.group]

    def test_keep_and_undo_integrate_with_exact_gate(self):
        # A retained copy passes the old checker; undo restores the original pending state.
        self.review.keep(self.group, self.ids[1])
        snapshot = self.review.snapshot()["groups"][0]
        self.assertEqual(snapshot["status"], "reviewed")
        self.assertTrue(snapshot["can_undo"])
        self.assertEqual(sum(f["present"] for f in snapshot["files"]), 1)
        self.assertTrue(all(f["available"] for f in snapshot["files"]))
        self.assertEqual(check(self.root, self.review.manifest, self.manifest), [])
        self.review.undo(self.group)
        self.assertEqual(self.review.snapshot()["groups"][0]["status"], "pending")
        self.assertEqual(len(list((self.base / "duplicated" / self.group).iterdir())), 3)

    def test_workflow_guide_rechecks_undo_and_bank_evidence(self):
        """Only verified steps turn green, and undo removes exact readiness."""
        self.assertFalse(any(step["checked"] for step in workflow_guide(None)["steps"]))
        self.assertEqual([step["checked"] for step in workflow_guide(self.review)["steps"]],
                         [True, False, False, False, False])
        self.review.keep(self.group, self.ids[0])
        steps = workflow_guide(self.review)["steps"]
        self.assertTrue(steps[1]["checked"])
        self.assertEqual(steps[1]["next"], "/content-review")
        bank = self.base / "bank-output"
        bank.mkdir()
        (bank / "master_statement.csv").write_text(
            "balance_checks,matching_status\npassed,pending\n", encoding="utf-8")
        steps = workflow_guide(self.review)["steps"]
        self.assertTrue(steps[3]["checked"])
        self.assertIsNone(steps[3]["next"])
        self.review.undo(self.group)
        self.assertFalse(workflow_guide(self.review)["steps"][1]["checked"])

    def test_changed_copy_blocks_choice(self):
        Path(self.review.records[self.ids[2]]["OrganizedPath"]).write_text("changed")
        with self.assertRaises(ValueError):
            self.review.keep(self.group, self.ids[0])
        self.assertEqual(len(list((self.base / "duplicated" / self.group).iterdir())), 3)

    def test_unexpected_copy_and_wrong_id_are_rejected(self):
        (self.base / "duplicated" / self.group / "extra.txt").write_text("extra")
        with self.assertRaises(ValueError):
            self.review.keep(self.group, self.ids[0])
        with self.assertRaises(ValueError):
            self.review.keep(self.group, "invalid-id")

    def test_recovery_survives_server_restart(self):
        self.review.keep(self.group, self.ids[0])
        restarted = Review(self.manifest, self.base / "dashboard-data")
        restarted.undo(self.group)
        self.assertEqual(restarted.snapshot()["groups"][0]["status"], "pending")

    def test_development_preset_replays_only_matching_exact_choice(self):
        """A named click restores a saved human choice on unchanged files."""
        self.review.keep(self.group, self.ids[1])
        self.assertEqual(development.remember(self.review)["exact"], 1)
        self.review.undo(self.group)
        with self.assertRaisesRegex(ValueError, "name"):
            development.apply(self.review, "")
        result = development.apply(self.review, "Admin")
        self.assertEqual(result["exact_applied"], 1)
        self.assertEqual(self.review.snapshot()["groups"][0]["kept"], self.ids[1])
        with patch.object(self.review, "snapshot", wraps=self.review.snapshot) as snapshot:
            self.assertEqual(development.apply(self.review, "Admin")["exact_applied"], 0)
            self.assertEqual(snapshot.call_count, 1)

    def test_completion_requires_bank_matching_and_reports_tokens(self):
        """Release final totals only after all workflow gates are complete."""
        self.review.keep(self.group, self.ids[0])
        work = self.base / "review"
        work.mkdir()
        (work / "index.json").write_text("{}", encoding="utf-8")
        record(work / "token-usage.jsonl", {"id": "one", "status": "finished", "stage": "pdf",
               "model": "test", "usage": {"input_tokens": 100, "cached_input_tokens": 20,
                                          "output_tokens": 25, "reasoning_output_tokens": 5}})
        with patch("reconciliation.vision_workflow.load", return_value=({}, {})), patch("reconciliation.vision_workflow.gate", return_value=[]):
            self.assertFalse(self.review.completion()["complete"])
            bank = self.base / "bank-output"
            bank.mkdir()
            (bank / "master_statement.csv").write_text("balance_checks,matching_status\npassed,matched\n", encoding="utf-8")
            result = self.review.completion()
        self.assertTrue(result["complete"])
        self.assertEqual(result["token_usage"]["totals"]["input_tokens"], 100)

    def test_bank_page_reads_master_and_serves_bank_only_workbook(self):
        """Show saved bank rows and expose only the known bank-only workbook."""
        self.assertFalse(self.review.bank_statement()["available"])
        bank = self.base / "bank-output"
        bank.mkdir()
        (bank / "master_statement.csv").write_text(
            "account,currency,opening_balance,closing_balance,total_money_in,total_money_out,balance_checks,transaction_id,date,page,direction,money_in,money_out,balance,counterparty,counterparty_role,narration,matching_status\n"
            "8866,MYR,100.00,110.00,10.00,0.00,passed,tx-1,2025-12-01,2,in,10.00,0.00,110.00,Payer,payer,Transfer,pending\n",
            encoding="utf-8")
        workbook = bank / "answer_statement_bank_only.xlsx"
        workbook.write_bytes(b"bank workbook fixture")
        server = TestServer(("127.0.0.1", 0), create_app(self.review, "test-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(url + "/api/bank-statement") as response:
            data = json.load(response)
        self.assertEqual((data["count"], data["matched"], data["transactions"][0]["counterparty"]),
                         (1, 0, "Payer"))
        self.assertTrue(data["workbook_available"])
        with urllib.request.urlopen(url + "/api/bank-workbook") as response:
            self.assertEqual(response.read(), b"bank workbook fixture")
        with urllib.request.urlopen(url + "/bank") as response:
            self.assertIn(b'id="app"', response.read())

    def test_altered_archive_blocks_undo(self):
        self.review.keep(self.group, self.ids[0])
        self.review.file_path(self.ids[1]).write_text("altered archive")
        with self.assertRaises(ValueError):
            self.review.undo(self.group)

    def test_http_requires_token_and_disallows_external_origins(self):
        # The local webpage can mutate fixtures; unrelated websites cannot.
        server = TestServer(("127.0.0.1", 0), create_app(self.review, "test-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        body = json.dumps({"group": self.group, "id": self.ids[0]}).encode()
        for headers in ({}, {"X-Review-Token": "test-token", "Origin": "https://example.com"}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url + "/api/keep", body, headers))
            self.assertEqual(error.exception.code, 403)
        request = urllib.request.Request(url + "/api/keep", body, {"X-Review-Token": "test-token", "Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(json.load(response)["reviewed"], 1)

    def test_vue_assets_and_direct_routes(self):
        """Known routes serve one shell and bundled assets remain local."""
        from dashboard.routes import FRONTEND
        server = TestServer(("127.0.0.1", 0), create_app(self.review, "test-token"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        for route in ("/", "/bank", "/documents", "/review", "/matching", "/extraction-review", "/settings"):
            with urllib.request.urlopen(base + route) as response:
                self.assertEqual(response.read(), (FRONTEND / "index.html").read_bytes())
        for asset in (FRONTEND / "assets").iterdir():
            with urllib.request.urlopen(base + "/assets/" + asset.name) as response:
                self.assertEqual(response.read(), asset.read_bytes())
                self.assertIn("immutable", response.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
