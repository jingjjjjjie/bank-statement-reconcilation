"""Check realistic review payloads without weakening control-request protection."""

import json
import threading
import urllib.error
import urllib.request
from copy import deepcopy

from dashboard.routes import MAX_EVIDENCE_REQUEST_BYTES, create_app
from tests.fixtures.receipt_review import ReceiptReviewFixture
from tests.http_server import TestServer


class EvidenceRequestTests(ReceiptReviewFixture):
    def setUp(self):
        """Serve twenty-six editable pieces in a disposable review."""
        super().setUp()
        values = []
        for number in range(26):
            piece = deepcopy(self.pieces[0])
            piece.update(total="1.00", brief_description=f"Payroll entry {number}: " + "x" * 400)
            values.append(piece)
        self.state["units"][self.key]["receipts"] = values
        self.save_state()
        self.review.data = self.base / "dashboard-data"
        self.review.root = self.base
        self.app = create_app(self.review, "fixture-token")
        server = TestServer(("127.0.0.1", 0), self.app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"

    def post(self, path, body, token="fixture-token"):
        """Submit the real browser JSON format and retain readable HTTP failures."""
        request = urllib.request.Request(
            self.base + path,
            json.dumps(body, ensure_ascii=False).encode("utf-8"),
            {"Content-Type": "application/json", "X-Review-Token": token},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def body(self):
        """Bind a full document edit to the current evidence revision."""
        view = self.view()
        return {"key": self.key, "revision": view["revision"], "receipts": view["units"][0]["receipts"]}

    def test_full_payroll_review_accepts_and_merges(self):
        """Full valid lists over eight KiB reach acceptance and merge validation."""
        body = self.body()
        self.assertGreater(len(json.dumps(body).encode()), 8192)
        status, _ = self.post("/api/receipts/accept", body)
        self.assertEqual(status, 200)
        accepted = self.view()["units"][0]
        self.assertTrue(accepted["accepted"])
        self.assertEqual(len(accepted["receipts"]), 26)
        status, merged = self.post("/api/receipts/merge-all", self.body())
        self.assertEqual(status, 200)
        self.assertEqual(merged["receipt"]["total"], "26.00")

    def test_large_edits_keep_revision_and_schema_validation(self):
        """Larger requests still cannot bypass stale evidence or invalid fields."""
        body = self.body()
        body["revision"] = "stale"
        status, error = self.post("/api/receipts/accept", body)
        self.assertEqual(status, 400)
        self.assertIn("changed", error["error"].lower())
        body = self.body()
        body["receipts"][0]["unexpected"] = True
        status, _ = self.post("/api/receipts/accept", body)
        self.assertEqual(status, 422)
        self.assertFalse(self.view()["units"][0]["accepted"])

    def test_bulk_accept_preserves_large_current_draft(self):
        """Accept all carries the same full document edit as individual acceptance."""
        body = self.body()
        status, result = self.post(
            "/api/receipts/accept-all",
            {"revision": body["revision"], "draft": {"key": body["key"], "receipts": body["receipts"]}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["bulk"]["accepted"], 1)
        self.assertEqual(len(self.view()["units"][0]["receipts"]), 26)

    def test_evidence_limit_and_authentication_still_reject(self):
        """Oversized evidence and unauthorized edits never reach saved decisions."""
        body = self.body()
        body["receipts"][0]["brief_description"] = "x" * MAX_EVIDENCE_REQUEST_BYTES
        self.assertEqual(self.post("/api/receipts/accept", body)[0], 413)
        self.assertEqual(self.post("/api/receipts/accept", body, token="wrong")[0], 403)
        self.assertFalse(self.view()["units"][0]["accepted"])
