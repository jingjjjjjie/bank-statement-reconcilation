"""Fresh Codex homes must support offline work without weakening catalog checks."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from reconciliation.document_reader import extract
from reconciliation.review_settings import DEFAULT_MODEL, DEFAULTS, load_config, revision, save_config, validate


class ModelCatalogTests(unittest.TestCase):
    """Exercise default settings with absent and authoritative model metadata."""

    def test_fresh_home_extracts_and_saves_default_settings(self):
        """A missing Codex cache permits real local extraction and settings roundtrips."""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with patch.dict("os.environ", {"CODEX_HOME": str(base / "codex")}):
                config = validate(dict(DEFAULTS))
                source = base / "receipt.png"
                Image.new("RGB", (20, 20)).save(source)
                self.assertEqual(len(extract(source, base / "units", config)), 1)
                path = base / "settings.json"
                save_config(path, config, revision(DEFAULTS))
                self.assertEqual(load_config(path), config)
                stages = {"images": {"model": DEFAULT_MODEL, "reasoning": "default"}}
                self.assertEqual(validate({**config, "stages": stages})["stages"], stages)

    def test_missing_catalog_rejects_unverified_overrides(self):
        """The fallback permits neither invented models nor reasoning overrides."""
        with patch("reconciliation.review_settings.model_catalog", return_value=[]):
            for choice in ({"model": "unknown"}, {"reasoning": "high"},
                           {"stages": {"images": {"model": "unknown", "reasoning": "default"}}}):
                with self.subTest(choice=choice), self.assertRaises(ValueError):
                    validate({**DEFAULTS, **choice})

    def test_available_catalog_remains_authoritative(self):
        """Known capability restrictions also apply to the project default."""
        models = [{"id": DEFAULT_MODEL, "reasoning": ["low"], "vision": False}]
        with patch("reconciliation.review_settings.model_catalog", return_value=models):
            with self.assertRaisesRegex(ValueError, "pictures"):
                validate(dict(DEFAULTS))
            with self.assertRaisesRegex(ValueError, "reasoning"):
                validate({**DEFAULTS, "pictures_enabled": False, "reasoning": "high"})
            models[0]["id"] = "another-model"
            with self.assertRaisesRegex(ValueError, "catalog"):
                validate(dict(DEFAULTS))
