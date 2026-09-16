"""Configuration checks use synthetic PDFs, images and temporary JSON files."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import pymupdf
from PIL import Image
from document_reader import extract
from review_settings import DEFAULTS, load_config, save_config, revision, validate, stage_settings
from vision_workflow import active_config, ReviewPending, run
from codex_reviewer import CodexReviewer, object_schema


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = self.base / "config.json"
        self.config = dict(DEFAULTS)
        self.pdf = self.base / "receipt.pdf"
        # Page one has native text; page two stands in for a textless scan.
        with pymupdf.open() as document:
            document.new_page().insert_text((30, 30), "Invoice TEST-001. Supplier Example. Total MYR 123.45.")
            document.new_page()
            document.save(self.pdf)

    def test_pdf_text_only_uses_no_page_images_and_blocks_scan(self):
        units = extract(self.pdf, self.base / "text", self.config)
        self.assertTrue(all(u["image"] is None for u in units))
        self.assertIn("123.45", units[0]["text"])
        self.assertFalse(units[0]["blocked"])
        self.assertTrue(units[0]["limitation"])
        self.assertTrue(units[1]["blocked"])

    def test_auto_renders_only_sparse_page(self):
        self.config["pdf_mode"] = "auto"
        units = extract(self.pdf, self.base / "auto", self.config)
        self.assertIsNone(units[0]["image"])
        self.assertTrue(Path(units[1]["image"]).exists())
        self.assertFalse(units[1]["blocked"])

    def test_picture_off_blocks_images_and_pdf_fallback(self):
        self.config.update(pdf_mode="auto", pictures_enabled=False)
        units = extract(self.pdf, self.base / "off", self.config)
        self.assertTrue(units[1]["blocked"])
        image = self.base / "image.png"
        Image.new("RGB", (30, 30)).save(image)
        units = extract(image, self.base / "image-off", self.config)
        self.assertTrue(units[0]["blocked"])
        self.assertIsNone(units[0]["image"])

    def test_settings_roundtrip_and_stale_save(self):
        before = revision(load_config(self.path))
        self.config["codex_enabled"] = False
        save_config(self.path, self.config, before)
        self.assertEqual(load_config(self.path), self.config)
        with self.assertRaisesRegex(ValueError, "changed elsewhere"):
            save_config(self.path, DEFAULTS, before)

    def test_invalid_settings_do_not_get_saved(self):
        for change in ({"codex_enabled": "false"}, {"max_calls": True}, {"max_calls": 0},
                       {"max_parallel": True}, {"max_parallel": 0}, {"max_parallel": 9},
                       {"pdf_mode": "typo"}, {"unknown": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate({**DEFAULTS, **change})
        self.assertFalse(self.path.exists())

    def test_codex_off_stops_before_any_model_work(self):
        self.config["codex_enabled"] = False
        save_config(self.path, self.config, revision(DEFAULTS))
        index = {"config_path": str(self.path), "config": dict(DEFAULTS)}
        with self.assertRaisesRegex(ReviewPending, "Codex is off"):
            run(self.base, index, {}, object())

    def test_extraction_change_invalidates_prepared_review(self):
        self.config["pictures_enabled"] = False
        save_config(self.path, self.config, revision(DEFAULTS))
        index = {"config_path": str(self.path), "config": dict(DEFAULTS)}
        with self.assertRaisesRegex(ReviewPending, "settings changed"):
            active_config(index)
        # Execution limits alone do not invalidate extraction.
        self.path.write_text(json.dumps({**DEFAULTS, "max_calls": 7}))
        self.assertEqual(active_config(index)["max_calls"], 7)

    def test_model_reasoning_and_vision_capabilities_are_validated(self):
        models = [{"id": "test-model", "reasoning": ["low", "high"], "vision": True}]
        with patch("review_settings.model_catalog", return_value=models):
            self.assertEqual(validate({**DEFAULTS, "model": "test-model", "reasoning": "high"})["reasoning"], "high")
            for choice in ({"model": "unknown"}, {"model": "test-model", "reasoning": "ultra"}, {"reasoning": "high"}):
                with self.assertRaises(ValueError):
                    validate({**DEFAULTS, **choice})
            models[0]["vision"] = False
            with self.assertRaisesRegex(ValueError, "pictures"):
                validate({**DEFAULTS, "model": "test-model"})

    def test_codex_receives_model_reasoning_and_caches_them_separately(self):
        # Inspect subprocess arguments with no live model calls.
        commands = []
        def fake_run(command, **kwargs):
            if command[1:3] == ["login", "status"]:
                return SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")
            commands.append(command)
            Path(command[command.index("--output-last-message") + 1]).write_text('{"ok": true}')
            return SimpleNamespace(returncode=0)
        schema = object_schema({"ok": {"type": "boolean"}})
        with patch("codex_reviewer.subprocess.run", side_effect=fake_run):
            for effort in ("low", "high", "low"):
                engine = CodexReviewer(self.base, executable="codex", model="gpt-5.6-sol", reasoning=effort)
                self.assertTrue(engine.ask("test", schema)["ok"])
        self.assertEqual(len(commands), 2)
        self.assertIn('model_reasoning_effort="high"', commands[1])
        self.assertEqual(commands[1][commands[1].index("--model") + 1], "gpt-5.6-sol")

    def test_stage_validation_and_legacy_fallback(self):
        models = [{"id": "text", "reasoning": ["low"], "vision": False},
                  {"id": "vision", "reasoning": ["high"], "vision": True}]
        with patch("review_settings.model_catalog", return_value=models):
            legacy = validate({**DEFAULTS, "model": "vision", "reasoning": "high"})
            self.assertTrue(all(c["model"] == "vision" for c in stage_settings(legacy).values()))
            config = {**DEFAULTS, "model": "vision", "stages": {"pdf": {"model": "text", "reasoning": "low"}}}
            self.assertEqual(stage_settings(validate(config))["pdf"]["model"], "text")
            for change in ({"pdf_mode": "vision"},
                           {"stages": {"images": {"model": "text", "reasoning": "low"}}},
                           {"stages": {"typo": {"model": "", "reasoning": "default"}}}):
                with self.assertRaises(ValueError):
                    validate({**config, **change})

    def test_switching_models_shares_budget_and_preserves_cache(self):
        from codex_reviewer import BudgetReached
        def fake_run(command, **kwargs):
            if command[1:3] == ["login", "status"]:
                return SimpleNamespace(returncode=0, stdout="ChatGPT", stderr="")
            Path(command[command.index("--output-last-message") + 1]).write_text('{"ok": true}')
            return SimpleNamespace(returncode=0)
        schema = object_schema({"ok": {"type": "boolean"}})
        engine = CodexReviewer(self.base, executable="codex", model="first", max_calls=1)
        with patch("codex_reviewer.subprocess.run", side_effect=fake_run):
            engine.ask("test", schema)
            engine.model = "second"
            with self.assertRaises(BudgetReached):
                engine.ask("test", schema)
            engine.model = "first"
            self.assertTrue(engine.ask("test", schema)["ok"])
        self.assertEqual(engine.calls, 1)


if __name__ == "__main__":
    unittest.main()
