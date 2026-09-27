"""Extraction workflow: preparation, completion gate, inventory, resume and settings safeguards."""
import copy
import csv
import hashlib
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pymupdf
from openpyxl import Workbook

import reconciliation.extraction.workflow as workflow
from reconciliation.core.prompts import load_prompt
from reconciliation.core.settings import DEFAULTS, STAGES
from reconciliation.extraction.schemas import EXTRACTION
from reconciliation.model.codex import CACHE_PROFILE, BudgetReached, CodexReviewer
from tests.fixtures.workflow import FakeReviewer, ReviewFixture


def is_extraction(schema):
    """True for the stored or the model-facing extraction schema."""
    from reconciliation.extraction.pieces import EXTRACTION as MODEL_EXTRACTION
    return schema in (EXTRACTION, MODEL_EXTRACTION)


class WorkflowTests(ReviewFixture, unittest.TestCase):
    def inventory(self):
        """Read supporting-inventory.csv rows."""
        with (self.work / "supporting-inventory.csv").open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_checkpoint_retries_a_brief_windows_lock(self):
        """A temporary sharing lock does not lose a saved checkpoint."""
        path, original, attempts = self.base / "state.json", Path.replace, [0]

        def briefly_locked(source, target):
            """Deny the first replacement and allow the retry."""
            attempts[0] += 1
            if attempts[0] == 1:
                raise PermissionError("file is in use")
            return original(source, target)

        with patch.object(Path, "replace", briefly_locked), patch("reconciliation.extraction.workflow.sleep"):
            workflow.save(path, {"units": 1})
        self.assertEqual(workflow.read(path), {"units": 1})
        self.assertEqual(attempts[0], 2)

    def test_run_completes_review_and_inventory(self):
        """Every unit is read once, the gate passes, and nested files stay listed."""
        nested = self.root / "deep" / "deeper"
        nested.mkdir(parents=True)
        (self.root / "b.png").rename(nested / "b.png")
        index, state = self.prepared()
        self.assertEqual({row["status"] for row in self.inventory()}, {"extraction_pending"})
        workflow.run(self.work, index, state, FakeReviewer())
        self.assertEqual(workflow.gate(index, state), [])
        rows = self.inventory()
        self.assertEqual({row["status"] for row in rows}, {"extracted"})
        self.assertTrue(any("deeper" in row["source_path"] for row in rows))
        self.assertEqual({row["invoice_numbers"] for row in rows}, {'["TEST-1"]'})
        self.assertIn("COMPLETE", (self.work / "report.md").read_text(encoding="utf-8"))

    def test_unsupported_files_are_listed_without_blocking(self):
        """Unsupported formats need no model call and do not hold up completion."""
        (self.root / "notes.txt").write_text("not a receipt", encoding="utf-8")
        index, state = self.prepared()
        workflow.run(self.work, index, state, FakeReviewer())
        self.assertEqual(workflow.gate(index, state), [])
        unsupported = next(row for row in self.inventory() if row["file_format"] == ".txt")
        self.assertEqual((unsupported["status"], unsupported["format_status"]), ("not_accepted", "not_accepted"))

    def test_exact_copies_are_listed_once_per_original(self):
        """Each exact copy keeps its own inventory row and names its twins."""
        nested = self.root / "deep"
        nested.mkdir()
        (nested / "copy.png").write_bytes((self.root / "a.png").read_bytes())
        self.prepared()
        rows = self.inventory()
        self.assertEqual(len(rows), 3)
        self.assertEqual(len([row for row in rows if row["exact_duplicate_with"] != "[]"]), 2)

    def test_saved_duplicate_removal_requires_cleanup_and_survivor(self):
        """Old admin decisions still gate completion until the removed copy is gone."""
        index, state = self.prepared()
        workflow.run(self.work, index, state, FakeReviewer())
        left, right = sorted(index["documents"])
        state["decisions"][f"{left}:{right}"] = {"verdict": "keep_left", "reviewer": "Admin", "reason": "Same"}
        self.assertTrue(any("cleanup pending" in p for p in workflow.gate(index, state)))
        Path(index["documents"][right]["paths"][0]).unlink()
        self.assertEqual(workflow.gate(index, state), [])
        workflow.report(self.work, index, state)
        self.assertEqual({row["status"] for row in self.inventory()}, {"extracted", "confirmed_duplicate"})
        Path(index["documents"][left]["paths"][0]).unlink()
        with self.assertRaises(ValueError):
            workflow.gate(index, state)

    def test_pending_exact_duplicates_block_model_calls(self):
        """Exact-copy cleanup must finish before any model call."""
        index, state = self.prepared(duplicate=True)
        with self.assertRaisesRegex(ValueError, "Pass-one"):
            workflow.run(self.work, index, state, FakeReviewer())
        self.assertEqual(state["units"], {})

    def test_budget_stop_keeps_review_incomplete_with_report(self):
        """Reaching the call limit leaves visible outstanding checks."""
        index, state = self.prepared()

        class LimitedReviewer(FakeReviewer):
            def ask(self, *args, **kwargs):
                raise BudgetReached("test limit")

        with self.assertRaises(BudgetReached):
            workflow.run(self.work, index, state, LimitedReviewer())
        self.assertTrue(workflow.gate(index, state))
        self.assertIn("PENDING", (self.work / "report.md").read_text(encoding="utf-8"))

    def test_refresh_keeps_validated_model_cache(self):
        """prepare --refresh reuses an identical completed Codex response without a new call."""
        self.prepared()
        prompt, model = "Cached fixture extraction", "fixture"
        key = hashlib.sha256(json.dumps([load_prompt("shared/styles") + "\n\n" + prompt, EXTRACTION, model, "default",
                                         CACHE_PROFILE], sort_keys=True).encode()).hexdigest()
        folder = self.work / "model-cache" / key
        folder.mkdir(parents=True)
        expected = FakeReviewer().ask(prompt, EXTRACTION)
        (folder / "result.json").write_text(json.dumps(expected), encoding="utf-8")
        workflow.prepare(self.manifest, self.work, refresh=True)
        reviewer = CodexReviewer(self.work, executable="missing-codex", model=model, max_calls=0)
        self.assertEqual(reviewer.ask(prompt, EXTRACTION), expected)
        self.assertEqual(reviewer.calls, 0)

    def test_parallel_units_complete_and_checkpoint(self):
        """Independent units run together and both results are saved."""
        index, state = self.prepared()
        barrier = threading.Barrier(2)

        class ParallelReviewer(FakeReviewer):
            def fork(self):
                return copy.copy(self)

            def ask(self, prompt, schema, images=()):
                if is_extraction(schema):
                    barrier.wait(timeout=5)
                return super().ask(prompt, schema, images)

        with patch("reconciliation.extraction.workflow.active_config", return_value={**DEFAULTS, "max_parallel": 2}):
            workflow.run(self.work, index, state, ParallelReviewer())
        self.assertEqual(len(workflow.load(self.work)[1]["units"]), 2)

    def test_parallel_failure_keeps_other_finished_work(self):
        """The job runner drains active jobs and saves successes before raising."""
        barrier, saved = threading.Barrier(2), []

        def stopped():
            barrier.wait(timeout=5)
            raise BudgetReached("limit")

        def finished():
            barrier.wait(timeout=5)
            return "finished"

        with self.assertRaises(BudgetReached):
            workflow.run_jobs([stopped, finished], saved.append, 2)
        self.assertEqual(saved, ["finished"])

    def test_modified_sources_and_previews_are_rejected(self):
        """Changed originals or page images invalidate the prepared review."""
        index, state = self.prepared()
        (self.root / "a.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Sources changed"):
            workflow.gate(index, state)
        unit = next(iter(index["documents"].values()))["units"][0]
        Path(unit["image"]).write_bytes(b"changed preview")
        with self.assertRaisesRegex(ValueError, "image changed"):
            workflow.load(self.work)

    def test_each_file_type_uses_its_stage_model_and_changes_block_resume(self):
        """PDF, Excel, image and Word units go to their own stage models; changed choices stop a resume."""
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((30, 30), "Invoice TEST-1 Total MYR 123.45")
            pdf.save(self.root / "invoice.pdf")
        book = Workbook()
        book.active["A1"] = "Invoice TEST-1 Total MYR 123.45"
        book.save(self.root / "invoice.xlsx")
        book.close()
        with ZipFile(self.root / "claim.docx", "w") as document:
            document.writestr("word/document.xml", '<w:document xmlns:w="urn:test"><w:t>Travel claim MYR 45.00</w:t></w:document>')
        index, state = self.prepared()
        choices = {stage: {"model": stage, "reasoning": "high"} for stage in STAGES}
        config = {**DEFAULTS, "stages": choices}
        calls = []

        class RecordingReviewer(FakeReviewer):
            def ask(self, prompt, schema, images=()):
                calls.append((self.model, self.reasoning, bool(images)))
                return super().ask(prompt, schema, images)

        with patch("reconciliation.extraction.workflow.active_config", return_value=config):
            workflow.run(self.work, index, state, RecordingReviewer())
            self.assertEqual({model for model, _, _ in calls}, {"images", "pdf", "excel", "word"})
            self.assertTrue(all(reasoning == "high" for _, reasoning, _ in calls))
            self.assertTrue(all(has_images for model, _, has_images in calls if model == "images"))
            changed = {**config, "stages": {**choices, "pdf": {"model": "different", "reasoning": "low"}}}
            with patch("reconciliation.extraction.workflow.active_config", return_value=changed):
                with self.assertRaisesRegex(workflow.ReviewPending, "Model or reasoning changed"):
                    workflow.run(self.work, index, state, RecordingReviewer())


if __name__ == "__main__":
    unittest.main()
