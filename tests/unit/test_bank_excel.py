"""Check reusable styles and bank-only export content without a sample workbook."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from openpyxl import load_workbook

from reconciliation.bank_excel import STYLE_PATH, export


class BankExcelTests(unittest.TestCase):
    """Exercise saved workbook values and live style changes."""

    def setUp(self):
        """Supply synthetic validated bank data independently of PDF extraction."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "answer.xlsx"
        row = {"date": "2026-01-02", "counterparty": "Example vendor", "money_in": "0",
               "money_out": "20", "balance": "80", "page": 2, "transaction_id": "test-1",
               "narration": "Synthetic transfer", "counterparty_role": "recipient",
               "counterparty_raw": "Example vendor"}
        data = {"account": "123", "currency": "MYR", "source": "statement.pdf",
                "opening_balance": "100", "total_money_in": "0", "total_money_out": "20",
                "transactions": [row]}
        mock = patch("reconciliation.bank_excel.read_master", return_value=data)
        mock.start()
        self.addCleanup(mock.stop)

    def test_export_preserves_bank_fields_and_captured_style(self):
        """The saved file contains evidence and formatting without sample data or formulas."""
        export(self.root / "master.csv", "Example company", self.output)
        book = load_workbook(self.output)
        self.addCleanup(book.close)
        sheet = book.active
        self.assertEqual(sheet.title, "JAN'26")
        self.assertEqual(sheet["A1"].value, "Example company")
        self.assertEqual(sheet["F6"].value, "EXAMPLE VENDOR")
        self.assertEqual(sheet["I6"].value, 20)
        self.assertEqual(sheet["J6"].value, 80)
        self.assertEqual(sheet["J5"].value, 100)
        self.assertEqual(sheet["K6"].value, "PENDING")
        self.assertEqual(sheet["I8"].value, 20)
        for column in (2, 3, 4, 5, 7):
            self.assertIsNone(sheet.cell(6, column).value)
        self.assertIsNone(sheet["H9"].value)
        self.assertIsNone(sheet["H10"].value)
        self.assertFalse(any(cell.data_type == "f" for row in sheet for cell in row))
        self.assertIn("test-1", sheet["A6"].comment.text)
        self.assertEqual(sheet["A6"].number_format, "dd/mm/yyyy")
        self.assertEqual(sheet["A1"].font.sz, 16)
        self.assertEqual(sheet.row_dimensions[6].height, 30)
        self.assertEqual(sheet.page_setup.orientation, "landscape")
        self.assertIsNotNone(book.loaded_theme)

    def test_style_edits_apply_to_next_export(self):
        """Changing the style file changes formatting without changing bank values."""
        path = self.root / "style.xml"
        tree = ET.parse(STYLE_PATH)
        style = tree.getroot()
        style.find("columns/column[@field='counterparty']").set("width", "42")
        style.find("row[@name='transaction']").set("height", "44")
        tree.write(path)
        export(self.root / "master.csv", "Example company", self.output, path)
        book = load_workbook(self.output)
        self.addCleanup(book.close)
        self.assertEqual(book.active.column_dimensions["F"].width, 42)
        self.assertEqual(book.active.row_dimensions[6].height, 44)
        self.assertEqual(book.active["J6"].value, 80)

    def test_missing_or_invalid_style_fails_export(self):
        """No hidden sample or fallback format masks a broken style definition."""
        path = self.root / "missing.xml"
        with self.assertRaises(FileNotFoundError):
            export(self.root / "master.csv", "Example company", self.output, path)
        path.write_text('<workbook-style version="99"/>')
        with self.assertRaisesRegex(ValueError, "Unsupported workbook style"):
            export(self.root / "master.csv", "Example company", self.output, path)
        self.assertFalse(self.output.exists())

    def test_reordered_columns_move_values_styles_totals_and_comments(self):
        """Reversing only the XML columns must keep each field and its evidence aligned."""
        path = self.root / "reordered.xml"
        tree = ET.parse(STYLE_PATH)
        columns = tree.getroot().find("columns")
        columns[:] = list(reversed(list(columns)))
        tree.write(path)
        export(self.root / "master.csv", "Example company", self.output, path)
        book = load_workbook(self.output)
        self.addCleanup(book.close)
        sheet = book.active
        self.assertEqual(sheet["A4"].value, "REMARK")
        self.assertEqual(sheet["A6"].value, "PENDING")
        self.assertTrue(sheet["A6"].font.bold)
        self.assertEqual(sheet["K4"].value, "DATE")
        self.assertEqual(sheet["K6"].number_format, "dd/mm/yyyy")
        self.assertIn("test-1", sheet["K6"].comment.text)
        self.assertEqual(sheet["B5"].value, 100)
        self.assertEqual(sheet["B6"].value, 80)
        self.assertEqual(sheet["C6"].value, 20)
        self.assertEqual(sheet["C8"].value, 20)
        self.assertEqual(sheet["E8"].value, "TOTAL")
        self.assertEqual(sheet["F6"].value, "EXAMPLE VENDOR")
        self.assertIn("recipient", sheet["F6"].comment.text)
        self.assertEqual(sheet["A1"].font.sz, 16)
        self.assertEqual(sheet["A1"].value, "Example company")
        for column in (5, 7, 8, 9, 10):
            self.assertIsNone(sheet.cell(6, column).value)

    def test_bad_mappings_fail_before_creating_output(self):
        """Typos, duplicate fields and broken style references cannot silently lose data."""
        for change in ("unknown", "duplicate", "missing", "broken_style"):
            with self.subTest(change=change):
                path = self.root / "invalid.xml"
                tree = ET.parse(STYLE_PATH)
                root = tree.getroot()
                columns = root.find("columns")
                if change == "unknown":
                    columns[0].set("field", "typo")
                elif change == "duplicate":
                    columns[0].set("field", columns[1].get("field"))
                elif change == "missing":
                    columns.remove(columns[0])
                else:
                    root.find("row/cell").set("style", "missing")
                tree.write(path)
                with self.assertRaises(ValueError):
                    export(self.root / "master.csv", "Example company", self.output, path)
                self.assertFalse(self.output.exists())
