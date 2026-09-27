"""Check candidate ranking rules and batching used by Generate matches."""

import unittest

from reconciliation.matching.ranking import path_amounts, rank

ROOT = "/uploads/work/documents"


def piece(key, document, amount, payee, folder="misc"):
    """A minimal stored piece as piece_matching.current builds it."""
    return key, {
        "id": key,
        "document": document,
        "amount": amount,
        "currency": "MYR",
        "parties": [payee],
        "typed_references": [],
        "references": [],
        "date": "",
        "dates": [],
        "description": "",
        "source_path": f"{ROOT}/{folder}/{document}.pdf",
    }


class RankTests(unittest.TestCase):
    def setUp(self):
        """Two RM 90 recipients, a two-receipt document and a filename-only bundle."""
        self.items = dict(
            [
                piece("p1", "sheet", "90.00", "Norhidayah Binti Norizal"),
                piece("p2", "sheet", "90.00", "Muhammad Firdaus Hakimi"),
                piece("p3", "receipts", "50.00", "LEU"),
                piece("p4", "receipts", "376.15", "PASAR MINI"),
                piece("p5", "postage", "22.71", "Pos Malaysia", folder="wing-192.80"),
                piece("p6", "tnb", "365.33", "Tenaga Nasional Berhad"),
            ]
        )
        self.documents = {"receipts": {"totals": [{"label": "SUM", "amount": "426.15"}]}}

    def ranked(self, bank_id, amount, name):
        """Rank one outgoing bank line."""
        bank = {"id": bank_id, "amount": amount, "currency": "MYR", "parties": [name], "description": "", "date": ""}
        return rank([bank], self.items, self.documents, ROOT)

    def test_common_amount_is_ordered_by_name(self):
        """With equal amounts the truncated bank name decides the order."""
        choices, audit = self.ranked("B1", "90.00", "NORHIDAYAH BINTI NORIZ")
        self.assertEqual(choices["B1"][:2], ["p1", "p2"])
        self.assertEqual(audit["B1"]["reasons"]["p1"]["route"], "amount")

    def test_sen_rounding_and_document_totals(self):
        """Five sen still matches; a multi-piece printed total offers all its pieces."""
        choices, audit = self.ranked("B2", "365.35", "TENAGA NASIONAL BERHAD")
        self.assertEqual(choices["B2"][0], "p6")
        self.assertEqual(audit["B2"]["reasons"]["p6"]["difference"], "0.02")
        choices, audit = self.ranked("B3", "426.15", "LEE CHIA KENG")
        self.assertEqual(set(choices["B3"]), {"p3", "p4"})
        self.assertEqual(audit["B3"]["reasons"]["p3"]["label"], "SUM")

    def test_filename_candidates_are_labelled_and_none_when_empty(self):
        """A folder amount finds pieces only as labelled filename candidates."""
        choices, audit = self.ranked("B4", "192.80", "PAN YINGSHI")
        self.assertEqual(choices["B4"], ["p5"])
        self.assertEqual(audit["B4"]["reasons"]["p5"]["route"], "found by filename")
        choices, audit = self.ranked("B5", "7777.77", "NOBODY")
        self.assertEqual((choices["B5"], audit["B5"]["route"]), ([], "none"))

    def test_path_amounts_skip_dates_and_stray_digits(self):
        """Dates and single digits in names are not amounts."""
        values = {str(v) for v, _ in path_amounts("20251203 192.8wing/wing1-5aba.jpeg")}
        self.assertEqual(values, {"192.80"})


class BatchTests(unittest.TestCase):
    def test_competing_lines_share_a_batch_and_over_allocation_is_flagged(self):
        """Lines sharing a candidate stay together; double use of one piece is downgraded."""
        from dashboard.services.piece_match_jobs import batches, over_allocated

        choices = {"B1": ["p1"], "B2": ["p9"], "B3": ["p1", "p2"]}
        self.assertIn(["B1", "B3"], [sorted(b) for b in batches(["B1", "B2", "B3"], choices, size=2)])
        rows = [
            {"bank_id": b, "assessment": "strong", "reason": "", "allocations": [{"item_id": "p1", "amount": "90"}]}
            for b in ("B1", "B3")
        ]
        over_allocated(rows, {"p1": {"amount": "90"}})
        self.assertTrue(all(row["assessment"] == "tentative" for row in rows))


class CheckedRowsTests(unittest.TestCase):
    def test_one_invalid_answer_keeps_the_rest_of_the_batch(self):
        """A bad allocation or a skipped line becomes tentative; valid lines are kept."""
        from dashboard.services.piece_match_jobs import checked_rows

        banks = {key: {"amount": "90", "currency": "MYR"} for key in ("B1", "B2", "B3")}
        items = {"p1": {"amount": "90", "currency": "MYR"}, "p2": {"amount": "90", "currency": ""}}
        allowed = {"B1": ["p1"], "B2": ["p2"], "B3": ["p1"]}
        result = {
            "decisions": [
                {
                    "bank_id": "B1",
                    "assessment": "strong",
                    "allocations": [{"item_id": "p1", "amount": "90"}],
                    "reason": "Same payee",
                },
                {
                    "bank_id": "B2",
                    "assessment": "strong",
                    "allocations": [{"item_id": "p2", "amount": "90"}],
                    "reason": "Guess",
                },
            ]
        }
        rows = {row["bank_id"]: row for row in checked_rows(result, ["B1", "B2", "B3"], allowed, banks, items)}
        self.assertEqual(rows["B1"]["assessment"], "strong")
        self.assertEqual(rows["B2"]["assessment"], "tentative")
        self.assertIn("currencies", rows["B2"]["reason"])
        self.assertIn("did not return", rows["B3"]["reason"])


if __name__ == "__main__":
    unittest.main()
