"""Retrieve 20 name and 20 amount candidates, with reference priority and text fallback."""

import re
import unicodedata
from collections import Counter
from datetime import datetime
from math import log

from reconciliation.core.money import normalize_currency
from reconciliation.matching.candidates import number, specific_name, truncated_name

STOP = {
    'fund',
    'transfer',
    'debit',
    'credit',
    'payment',
    'receipt',
    'invoice',
    'fee',
    'sdn',
    'bhd',
    'ltd',
    'pty',
    'the',
    'and',
    'myr',
    'rm',
    'bank',
}
REFERENCE_TYPES = {'invoice', 'receipt', 'payment', 'transaction', 'booking', 'order', 'claim', 'document'}

#: Candidates kept per bank line: every exact reference, the best name and amount matches, then a text top-up.
NAME_CANDIDATES, AMOUNT_CANDIDATES, MAX_CANDIDATES, TEXT_TOP_UP = 20, 20, 40, 10
#: A usable reference has at least this many characters and one digit.
MIN_REFERENCE_CHARS = 4
#: Standard BM25 text-relevance parameters (term saturation k1, length normalization b).
BM25_K1, BM25_B = 1.2, 0.75


def words(text):
    """Tokenize literal source text without guessing translations or identities."""
    return [
        w
        for w in re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold())
        if w not in STOP and not w.isdecimal() and len(w) > 1
    ]


def normalize_reference(value):
    """Ignore case and whitespace while preserving punctuation and leading zeros."""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


def references(record):
    """Trust typed or explicitly labelled transaction IDs, not tax/account identifiers."""
    result = set()
    for entry in record.get('typed_references', record.get('references', [])):
        if isinstance(entry, dict):
            kind = entry.get('type', '').casefold().replace('_number', '').replace('_reference', '')
            value = entry.get('value', '') if kind in REFERENCE_TYPES else ''
        else:
            match = re.fullmatch(
                r'(invoice|receipt|payment|transaction|booking|order|claim)'
                r'\s*(?:number|no\.?|id|reference|ref\.?)?\s*[:#]\s*(.+)',
                entry,
                re.I,
            )
            value = (
                match[2] if match else (entry if re.fullmatch(r'(?:INV|RCP|BKG|PAY|TXN)[-/]\S+', entry, re.I) else '')
            )
        value = normalize_reference(value)
        if len(value) >= MIN_REFERENCE_CHARS and any(c.isdigit() for c in value):
            result.add(value)
    return result


def exact_references(bank, item):
    """Match complete source IDs to typed bank IDs or bounded IDs in bank narration."""
    bank_ids = references(bank)
    narration = unicodedata.normalize('NFKC', bank.get('description', '')).casefold()
    found = set()
    for value in references(item):
        pattern = r'(?<![\w/.-])' + r'\s*'.join(re.escape(c) for c in value) + r'(?![\w/.-])'
        if value in bank_ids or re.search(pattern, narration):
            found.add(value)
    return sorted(found)


class ReferenceIndex:
    """Prepare source reference patterns once for a complete ranking pass."""

    def __init__(self, items):
        """Retain the exact reference boundaries used by source matching."""
        self.items = {
            key: [
                (value, re.compile(r'(?<![\w/.-])' + r'\s*'.join(re.escape(c) for c in value) + r'(?![\w/.-])'))
                for value in references(item)
            ]
            for key, item in items.items()
        }

    def query(self, bank):
        """Normalize the bank once and return its exact source references per piece."""
        bank_ids = references(bank)
        narration = unicodedata.normalize('NFKC', bank.get('description', '')).casefold()
        return {
            key: sorted(value for value, pattern in patterns if value in bank_ids or pattern.search(narration))
            for key, patterns in self.items.items()
        }


def dates(record):
    """Read unambiguous dates for tie-breaking; retain unparsed dates in model evidence."""
    result = []
    for value in [record.get('date', ''), *record.get('dates', [])]:
        value = value.get('value', '') if isinstance(value, dict) else value
        for pattern in ('%Y-%m-%d', '%d %b %Y', '%d %B %Y', '%Y年%m月%d日'):
            try:
                result.append(datetime.strptime(value.strip(), pattern).date())
                break
            except (ValueError, TypeError):
                continue
    return result


def retrieve(banks, items):
    """Return bounded IDs and auditable coverage; scores order retrieval, never approval."""
    available = {i['id']: i for i in items if not i.get('excluded') and not i.get('retired')}
    corpus = {
        key: Counter(words(' '.join([item.get('description', ''), item.get('payee', ''), *item.get('parties', [])])))
        for key, item in available.items()
    }
    frequency = Counter(word for counts in corpus.values() for word in counts)
    average = sum(sum(c.values()) for c in corpus.values()) / max(1, len(corpus)) or 1
    choices, audit = {}, {}
    for bank in banks:
        query = set(words(bank.get('description', ''))) - set(words(' '.join(bank.get('parties', []))))
        bank_dates = dates(bank)
        rows = {}
        for key, item in available.items():
            ref = exact_references(bank, item)
            conflict = bool(
                (
                    item.get('currency')
                    and bank.get('currency')
                    and normalize_currency(item['currency']) != normalize_currency(bank['currency'])
                )
                or (item.get('direction') and bank.get('direction') and item['direction'] != bank['direction'])
            )
            if conflict and not ref:
                continue
            counts = corpus[key]
            score = sum(
                log(1 + (len(corpus) - frequency[w] + 0.5) / (frequency[w] + 0.5))
                * counts[w]
                * (BM25_K1 + 1)
                / (counts[w] + BM25_K1 * (1 - BM25_B + BM25_B * sum(counts.values()) / average))
                for w in query & counts.keys()
            )
            same_amount = number(bank.get('amount')) is not None and number(bank['amount']) == number(
                item.get('amount')
            )
            name = specific_name(bank.get('parties', []), item.get('parties', []))
            name = name or (same_amount and truncated_name(bank.get('parties', []), item.get('parties', [])))
            gap = min((abs((a - b).days) for a in bank_dates for b in dates(item)), default=10**9)
            rows[key] = {
                'exact_references': ref,
                'name': name,
                'amount': same_amount,
                'bm25': score,
                'date_distance_days': gap if gap < 10**9 else None,
                'conflict': conflict,
                'order': (-bool(ref), -score, gap, key),
            }
        ordered = sorted(rows, key=lambda key: rows[key]['order'])
        refs = [k for k in ordered if rows[k]['exact_references']]
        names = [k for k in ordered if rows[k]['name'] and not rows[k]['conflict']]
        amounts = [k for k in ordered if rows[k]['amount'] and not rows[k]['conflict']]
        primary = set(refs + names[:NAME_CANDIDATES] + amounts[:AMOUNT_CANDIDATES])
        selected = [k for k in ordered if k in primary][:MAX_CANDIDATES]
        fallback = [k for k in ordered if k not in primary and rows[k]['bm25'] > 0 and not rows[k]['conflict']]
        selected += fallback[: max(0, TEXT_TOP_UP - len(selected))]
        eligible = set(refs + names + amounts + fallback)
        choices[bank['id']] = selected
        audit[bank['id']] = {
            'policy': 'references-20-name-20-amount-top-up-10-v1',
            'name_matches': len(names),
            'amount_matches': len(amounts),
            'reference_matches': len(refs),
            'selected': len(selected),
            'eligible': len(eligible),
            'omitted': len(eligible - set(selected)),
            'search_incomplete': bool(eligible - set(selected)),
            'reference_overflow': len(refs) > MAX_CANDIDATES,
            'reasons': {k: {field: value for field, value in rows[k].items() if field != 'order'} for k in selected},
        }
    return choices, audit
