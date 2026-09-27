"""Ensure package organization does not relocate existing workflow state."""
import unittest
from pathlib import Path

from reconciliation.core.paths import WORKSPACE
from reconciliation.core.settings import CONFIG_PATH
from reconciliation.extraction.workflow import DEFAULT_WORK
from reconciliation.intake.duplicates import DEFAULT_MANIFEST


class WorkspacePathTests(unittest.TestCase):
    def test_default_state_stays_at_workspace_root(self):
        """Existing manifests, configuration, and review checkpoints stay discoverable."""
        root = Path(__file__).resolve().parents[3]
        self.assertEqual(WORKSPACE, root)
        self.assertEqual(DEFAULT_MANIFEST, root / "duplicate-manifest.json")
        self.assertEqual(CONFIG_PATH, root / "config" / "review_config.json")
        self.assertEqual(DEFAULT_WORK, root / "review")
