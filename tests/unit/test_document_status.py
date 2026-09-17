"""Check visibility metadata against saved human duplicate decisions."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.document_status import snapshot


class DocumentStatusTests(unittest.TestCase):
    def test_only_rejected_copy_is_marked_and_undo_restores_visibility(self):
        """Model matches alone never hide documents or alter source files."""
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "review").mkdir()
            (base / "review/index.json").write_text("{}")
            review = SimpleNamespace(manifest_path=base / "manifest.json")
            documents = {}
            for digest in ("left", "right"):
                source = base / (digest + ".txt")
                source.write_text(digest)
                documents[digest] = {"paths": [str(source)], "units": [], "error": ""}
            index = {"manifest": str(review.manifest_path), "documents": documents}
            state = {"units": {}, "screens": {"left:right": {"candidate": True}},
                     "pairs": {"left:right": {"classification": "same_document"}}, "decisions": {}}
            with patch("dashboard.document_status.load", return_value=(index, state)):
                for verdict, expected in ((None, set()), ("keep_left", {"right"}),
                                          ("keep_right", {"left"}), ("keep_both", set()), (None, set())):
                    state["decisions"] = {"left:right": {"verdict": verdict}} if verdict else {}
                    rows = snapshot(review)["documents"]
                    self.assertEqual({row["id"] for row in rows if row["approved_duplicate"]}, expected)
            for digest in documents:
                self.assertEqual((base / (digest + ".txt")).read_text(), digest)
