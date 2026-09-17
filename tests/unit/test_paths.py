"""Ensure package organization does not relocate existing workflow state."""
import unittest
from pathlib import Path

from reconciliation.duplicate_workflow import DEFAULT_MANIFEST
from reconciliation.paths import WORKSPACE
from reconciliation.review_settings import CONFIG_PATH
from reconciliation.vision_workflow import DEFAULT_WORK


class WorkspacePathTests(unittest.TestCase):
    def test_default_state_stays_at_workspace_root(self):
        """Existing manifests, configuration, and review checkpoints stay discoverable."""
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(WORKSPACE, root)
        self.assertEqual(DEFAULT_MANIFEST, root / "duplicate-manifest.json")
        self.assertEqual(CONFIG_PATH, root / "config" / "review_config.json")
        self.assertEqual(DEFAULT_WORK, root / "review")
