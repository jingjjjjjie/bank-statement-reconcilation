"""Deterministic candidate retrieval shared by live matching and historical experiments."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import itertools
import re
from reconciliation.currencies import normalize_currency


def number(value):
    """Normalize known amounts while keeping missing values distinct from zero."""
    try:
        result = Decimal(value) if value else None
        return result if result is not None and result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def tokens(value):
    """Normalize searchable text without guessing aliases or translating names."""
    return set(re.findall(r"[\w]+", value.casefold())) - {"sdn", "bhd", "the", "bank", "myr"}


def specific_name(left, right):
    """Compare whole names, ignoring honorifics and spacing, rather than one shared word."""
    ignored = {"cik", "puan", "encik", "bin", "binti", "bt", "bint", "berhad"}
    for a in left:
        at = tokens(a) - ignored
        for b in right:
            bt = tokens(b) - ignored
            if not at or not bt:
                continue
            if at == bt or (len(at & bt) >= 2 and len(at & bt) / min(len(at), len(bt)) >= .8):
                return True
            if "".join(sorted(at)) == "".join(sorted(bt)):
                return True
    return False


def build_candidates(banks, documents, grouped=True, specific=False):
    """Use amount/reference/name indexes, then bounded groups with explicit claim provenance."""
    expenses = defaultdict(list)
    for doc in documents:
        expenses[doc.get("expense_id") or doc["id"]].append(doc)
    pool = {}
    for parts in expenses.values():
        first = parts[0]
        candidate = {**first, "document_ids": [p["id"] for p in parts], "kind": "expense"}
        pool[first["id"]] = candidate
    by_amount, by_ref, by_name = defaultdict(set), defaultdict(set), defaultdict(set)
    for key, candidate in pool.items():
        if number(candidate["amount"]) is not None:
            by_amount[number(candidate["amount"])].add(key)
        for ref in candidate["references"]:
            by_ref[ref.casefold()].add(key)
        for token in tokens(" ".join(candidate["parties"])):
            by_name[token].add(key)
    choices = {}
    evaluations = 0
    for bank in banks:
        names = tokens(" ".join(bank["parties"]))
        refs = {r.casefold() for r in bank["references"]}
        keys = set(by_amount[number(bank["amount"])])
        for ref in refs:
            keys.update(by_ref[ref])
        for name in names:
            keys.update(by_name[name])
        ranked = []
        for key in keys:
            c = pool[key]
            evaluations += 1
            if (c["direction"] and c["direction"] != bank["direction"] or
                    c["currency"] and normalize_currency(c["currency"]) != normalize_currency(bank["currency"])):
                continue
            shared_refs = refs & {r.casefold() for r in c["references"]}
            reference = bool(shared_refs)
            name = bool(names & tokens(" ".join(c["parties"])))
            if specific:
                # Ordinary words such as SHOPEE are not transaction identifiers.
                reference = any(any(char.isdigit() for char in ref) for ref in shared_refs)
                name = specific_name(bank["parties"], c["parties"])
            exact = number(c["amount"]) == number(bank["amount"])
            truncated = specific and exact and truncated_name(bank["parties"], c["parties"])
            if not (reference or name or exact):
                continue
            # Reimbursements can name the claimant rather than the receipt merchant.
            # Exact amounts outrank name-only hits for retrieval, never for approval.
            score = 100 * reference + 30 * name + 40 * exact + 20 * truncated
            ranked.append((score, key))
        if grouped:
            groups = defaultdict(list)
            for _, key in ranked:
                if pool[key].get("claim_group") and number(pool[key]["amount"]) is not None:
                    groups[pool[key]["claim_group"]].append(key)
            for group, members in groups.items():
                # Small explicit groups only; large groups require a dedicated reconciliation.
                if len(members) > 12:
                    continue
                for size in range(2, len(members) + 1):
                    for subset in itertools.combinations(sorted(members), size):
                        if sum(number(pool[k]["amount"]) for k in subset) != number(bank["amount"]):
                            continue
                        key = "G-" + hashlib.sha256("|".join(subset).encode()).hexdigest()[:12]
                        pool[key] = {**pool[subset[0]], "id": key, "kind": "group",
                                     "amount": bank["amount"],
                                     "document_ids": [d for k in subset for d in pool[k]["document_ids"]]}
                        ranked.append((160, key))
        choices[bank["id"]] = sorted(set(ranked), key=lambda item: (-item[0], item[1]))
    return pool, choices, evaluations


def truncated_name(bank_names, source_names):
    """Retrieve exact-amount rows with an anchored, truncated final bank-name token."""
    ignored = {"cik", "puan", "encik", "bin", "binti", "bt", "bint", "berhad"}
    for bank in bank_names:
        left = [word for word in re.findall(r"[\w]+", bank.casefold()) if word not in ignored]
        for source in source_names:
            right = [word for word in re.findall(r"[\w]+", source.casefold()) if word not in ignored]
            if (len(left) >= 2 and len(left) == len(right) and left[:-1] == right[:-1]
                    and len(left[-1]) >= 5 and right[-1] != left[-1] and right[-1].startswith(left[-1])):
                return True
    return False


def shortlist(ranked, policy):
    """Compare fixed cutoffs with tie-preserving expansion to at most twelve options."""
    if policy != "adaptive":
        return ranked[:int(policy)]
    if len(ranked) <= 5:
        return ranked
    cutoff = ranked[4][0]
    return [item for item in ranked if item[0] >= cutoff][:12]
