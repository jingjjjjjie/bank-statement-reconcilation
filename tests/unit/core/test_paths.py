"""Ensure package organization does not relocate existing workflow state."""

import unittest
from pathlib import Path
from unittest.mock import patch

from reconciliation.core.paths import WORKSPACE
from reconciliation.core.prompts import PROMPTS
from reconciliation.core.settings import CONFIG_PATH
from reconciliation.extraction.workflow import DEFAULT_WORK, active_config
from reconciliation.intake.duplicates import DEFAULT_MANIFEST


class WorkspacePathTests(unittest.TestCase):
    def test_default_state_stays_at_workspace_root(self):
        """Existing manifests, configuration, and review checkpoints stay discoverable."""
        root = Path(__file__).resolve().parents[3]
        self.assertEqual(WORKSPACE, root)
        self.assertEqual(DEFAULT_MANIFEST, root / "duplicate-manifest.json")
        self.assertEqual(CONFIG_PATH, root / "resources" / "review_config.json")
        self.assertEqual(DEFAULT_WORK, root / "review")
        self.assertEqual(PROMPTS, root / "resources" / "prompts")

    def test_saved_legacy_config_path_resolves_to_resources(self):
        """Old review snapshots read the relocated shared settings without being rewritten."""
        settings = {"pdf_mode": "vision", "pictures_enabled": True}
        index = {"config_path": str(WORKSPACE / "config/review_config.json"), "config": settings}
        with patch("reconciliation.extraction.workflow.load_config", return_value=settings) as load:
            self.assertEqual(active_config(index), settings)
        load.assert_called_once_with(CONFIG_PATH)
        self.assertEqual(index["config_path"], str(WORKSPACE / "config/review_config.json"))
