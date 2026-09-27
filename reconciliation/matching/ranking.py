"""Rank candidate evidence for each bank line: amount matches, then name matches, then filename matches."""
import math
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import PurePath

from reconciliation.core.money import normalize_currency
from reconciliation.matching.candidates import number
from reconciliation.matching.retrieval import dates, exact_references

TOLERANCE = Decimal("0.05")   # Sen rounding (e.g. Penggenapan) still flags the difference in review.
CONTENT_SLOTS = 30            # Amount and name matches.
FILENAME_SLOTS = 10           # Extra pieces found only because a folder or file name shows the amount.
NAME_MATCH = 0.35             # Trigram similarity counted as a name match.
IGNORED = {"BIN", "BINTI", "BINT", "BT", "A/P", "A/L", "AP", "AL", "SDN", "BHD", "BERHAD", "CIK", "ENCIK", "PUAN"}
# Agencies are printed by acronym on documents but by full name on bank lines.
ALIASES = {"KWSP": "KUMPULAN WANG SIMPANAN PEKERJA", "EPF": "KUMPULAN WANG SIMPANAN PEKERJA",
           "PERKESO": "PERTUBUHAN KESELAMATAN SOSIAL", "SOCSO": "PERTUBUHAN KESELAMATAN SOSIAL",
           "EIS": "PERTUBUHAN KESELAMATAN SOSIAL", "LHDN": "LEMBAGA HASIL DALAM NEGERI", "PCB": "LEMBAGA HASIL DALAM NEGERI",
           "HRDF": "PEMBANGUNAN SUMBER MANUSIA BERHAD", "HRD CORP": "PEMBANGUNAN SUMBER MANUSIA BERHAD",
           "TNB": "TENAGA NASIONAL BERHAD"}


def names(values):
    """Expand names with agency aliases so acronyms meet full bank names."""
    result = []
    for value in values:
        if value:
            result.append(value)
            result.extend(full for short, full in ALIASES.items() if re.search(rf"\b{re.escape(short)}\b", value.upper()))
    return result


def grams(value):
    """Three-letter chunks of a name, ignoring honorifics, spacing and punctuation."""
    words = [w for w in re.findall(r"[A-Z0-9/]+", unicodedata.normalize("NFKC", value).upper()) if w not in IGNORED]
    text = " " + " ".join(words) + " "
    return Counter(text[i:i + 3] for i in range(len(text) - 2))


class NameIndex:
    """IDF-weighted trigram cosine similarity, which tolerates truncation and spacing."""

    def __init__(self, items):
        vectors = {key: grams(" ".join(names(item.get("parties", [])))) for key, item in items.items()}
        frequency = Counter(g for vector in vectors.values() for g in vector)
        self.default = math.log(1 + len(vectors))
        self.idf = {g: math.log(1 + len(vectors) / count) for g, count in frequency.items()}
        self.items = {key: self.unit(vector) for key, vector in vectors.items()}

    def unit(self, vector):
        """Weight chunks by rarity and scale to length one."""
        weighted = {g: count * self.idf.get(g, self.default) for g, count in vector.items()}
        norm = math.sqrt(sum(v * v for v in weighted.values())) or 1
        return {g: v / norm for g, v in weighted.items()}

    def query(self, bank_names):
        """Prepare a bank line's names once."""
        return [self.unit(grams(name)) for name in names(bank_names)]

    def similarity(self, query, key):
        """Best cosine similarity between any bank name and the piece's names (0 to 1)."""
        right = self.items[key]
        return max((sum(v * right.get(g, 0) for g, v in left.items()) for left in query), default=0.0)


def path_amounts(path):
    """Amounts written in a relative folder or file name, e.g. '报销 1,316.18' or 'wing1-192.80'."""
    found = set()
    for part in PurePath(path).parts:
        for token in re.findall(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|(?<![\d.])\d+\.\d{1,2}(?![\d])|(?<![\d.])\d+(?![\d.])", part):
            value = number(token.replace(",", ""))
            # Skip yyyymmdd dates and single digits such as the 1 in "wing1".
            if re.fullmatch(r"20\d{6}", token) or (value is not None and value < 10 and "." not in token):
                continue
            if value is not None and value > 0:
                found.add((value.quantize(Decimal("0.01")), part))
    return found


def rank(banks, items, documents, root=""):
    """Return ordered candidate IDs and an auditable reason for every bank line."""
    live = {key: item for key, item in items.items() if not item.get("excluded") and not item.get("retired")}
    index = NameIndex(live)
    by_document = defaultdict(list)
    for key, item in live.items():
        by_document[item["document"]].append(key)
    # Document totals: printed totals, or the sum of pieces, for documents with several pieces.
    totals = {}
    for digest, keys in by_document.items():
        if len(keys) < 2:
            continue
        printed = [(number(str(t.get("amount", "")).replace(",", "")), t.get("label", "Total"))
                   for t in documents.get(digest, {}).get("totals", [])]
        printed = [(value, label) for value, label in printed if value is not None]
        pieces_sum = sum((number(live[k]["amount"]) or Decimal(0)) for k in keys)
        totals[digest] = printed or [(pieces_sum, "sum of pieces")]
    # Filename amounts per document, from its path relative to the upload root.
    in_path = defaultdict(list)
    for digest, keys in by_document.items():
        path = str(PurePath(live[keys[0]]["source_path"]).relative_to(root)) if root and live[keys[0]]["source_path"].startswith(root) else live[keys[0]]["source_path"]
        for value, part in path_amounts(path):
            in_path[value].append((digest, part))
    common = Counter(number(item["amount"]).quantize(Decimal("0.01")) for item in live.values() if number(item["amount"]) is not None)

    choices, audit = {}, {}
    for bank in banks:
        key, value = bank["id"], number(bank.get("amount"))
        bank_dates = dates(bank)
        query = index.query(bank.get("parties", []))
        rows = {}   # candidate id -> reason
        units = []  # (sort key, [ids], reason)

        def compatible(item):
            """Unknown currencies stay eligible; conflicting ones do not."""
            return not (item.get("currency") and bank.get("currency")
                        and normalize_currency(item["currency"]) != normalize_currency(bank["currency"]))

        for item_key, item in live.items():
            if not compatible(item):
                continue
            name = index.similarity(query, item_key)
            reference = exact_references(bank, item)
            gap = min((abs((a - b).days) for a in bank_dates for b in dates(item)), default=None)
            item_value = number(item["amount"])
            amount_match = value is not None and item_value is not None and abs(value - item_value) <= TOLERANCE
            if amount_match or reference:
                units.append(((0, -bool(reference), -name, gap if gap is not None else 10 ** 6, item_key), [item_key], {
                    "route": "amount" if amount_match else "reference", "difference": str(value - item_value) if amount_match else "",
                    "shared_amount": common[item_value.quantize(Decimal("0.01"))] if item_value is not None else 0,
                    "name": round(name, 2), "references": reference}))
            elif name >= NAME_MATCH:
                units.append(((2, 0, -name, gap if gap is not None else 10 ** 6, item_key), [item_key], {
                    "route": "name", "name": round(name, 2)}))
        for digest, labelled in totals.items():
            hit = next(((total, label) for total, label in labelled if value is not None and abs(value - total) <= TOLERANCE), None)
            if hit:
                keys = [k for k in by_document[digest] if compatible(live[k])]
                name = max((index.similarity(query, k) for k in keys), default=0)
                # Document totals follow single pieces with the same amount.
                units.append(((1, 0, -name, 10 ** 6, digest), keys, {
                    "route": "document total", "label": hit[1], "difference": str(value - hit[0]), "name": round(name, 2)}))
        units.sort(key=lambda unit: unit[0])
        selected, eligible = [], set()
        for _, ids, reason in units:
            eligible.update(ids)
            if len(selected) < CONTENT_SLOTS and not set(ids) <= set(selected):
                for item_id in ids:
                    if item_id not in selected:
                        selected.append(item_id)
                        rows[item_id] = reason
        # Up to ten further pieces found only through the amount in a folder or file name.
        filename = []
        if value is not None:
            for digest, part in in_path.get(value.quantize(Decimal("0.01")), []):
                for item_id in by_document[digest]:
                    if item_id not in selected and item_id not in filename and compatible(live[item_id]) and len(filename) < FILENAME_SLOTS:
                        filename.append(item_id)
                        rows[item_id] = {"route": "found by filename", "filename": part}
        choices[key] = selected + filename
        omitted = len(eligible - set(selected))
        audit[key] = {"policy": "amount-then-name-30-plus-filename-10-v1",
                      "route": "model" if choices[key] else "none",
                      "amount_matches": sum(1 for _, _, r in units if r["route"] == "amount"),
                      "document_totals": sum(1 for _, _, r in units if r["route"] == "document total"),
                      "name_matches": sum(1 for _, _, r in units if r["route"] == "name"),
                      "filename_matches": len(filename), "selected": len(choices[key]), "eligible": len(eligible) + len(filename),
                      "omitted": omitted, "search_incomplete": bool(omitted), "reference_overflow": False, "reasons": rows}
    return choices, audit
