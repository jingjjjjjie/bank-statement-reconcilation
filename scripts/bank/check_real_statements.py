"""Re-extract local real bank statements and report any change from their saved baseline.

Customer PDFs and results stay in the git-ignored docs/local/ folder. Usage:
  python -m scripts.bank.check_real_statements --add "statement.pdf" 2025   # register and baseline
  python -m scripts.bank.check_real_statements                              # compare all
  python -m scripts.bank.check_real_statements --accept                     # keep intended changes
"""

import argparse
import json
from pathlib import Path

from reconciliation.bank.statement import extract, payees

STORE = Path(__file__).resolve().parents[2] / 'docs' / 'local' / 'real-statements.json'
TOTALS = ('opening_balance', 'total_money_in', 'total_money_out', 'closing_balance')


def snapshot(path, year):
    """Extract one statement into its bank, totals and per-row payees, or the reason it stopped."""
    try:
        result = extract(Path(path), year, 'auto')
    except (ValueError, OSError) as error:
        return {'error': str(error)}
    rows = result['transactions']
    return {
        'bank': result['bank'],
        'rows': len(rows),
        'totals': [str(result[key]) for key in TOTALS],
        'payees': [field['counterparty'] for field in payees(rows, result['bank'])],
    }


def changes(old, new):
    """List how a snapshot differs from its baseline."""
    if 'error' in old or 'error' in new:
        return [] if old == new else [f"was: {old.get('error', 'passing')} | now: {new.get('error', 'passing')}"]
    notes = [f'{key}: {old[key]} -> {new[key]}' for key in ('bank', 'rows', 'totals') if old[key] != new[key]]
    if not notes:
        pairs = enumerate(zip(old['payees'], new['payees']), 1)
        notes = [f'row {i} payee: {a or "REVIEW"!r} -> {b or "REVIEW"!r}' for i, (a, b) in pairs if a != b]
    return notes


def summary(shot):
    """Describe one snapshot in a single line."""
    if 'error' in shot:
        return f"STOPPED: {shot['error']}"
    blank = shot['payees'].count('')
    return f"{shot['bank']}, {shot['rows']} rows, {blank} REVIEW PAY TO"


def main():
    """Register new statements, compare every statement with its baseline, and exit 1 on change."""
    parser = argparse.ArgumentParser(description='Check real bank statements against their saved baseline.')
    parser.add_argument('--add', nargs=2, action='append', default=[], metavar=('PDF', 'YEAR'))
    parser.add_argument('--accept', action='store_true', help='save the current results as the baseline')
    args = parser.parse_args()
    store = json.loads(STORE.read_text(encoding='utf-8')) if STORE.exists() else {}
    for path, year in args.add:
        store.setdefault(str(Path(path).resolve()), {'year': int(year), 'baseline': None})

    changed = False
    for path, entry in store.items():
        current = snapshot(path, entry['year'])
        if entry['baseline'] is None or args.accept:
            notes = [] if entry['baseline'] is None else changes(entry['baseline'], current)
            entry['baseline'] = current
            print(f'SAVED   {Path(path).name}: {summary(current)}')
        else:
            notes = changes(entry['baseline'], current)
            changed |= bool(notes)
            print(f"{'CHANGED' if notes else 'same':7} {Path(path).name}: {summary(current)}")
        for note in notes[:15]:
            print(f'          {note}')
        if len(notes) > 15:
            print(f'          ... {len(notes) - 15} more')

    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, indent=1, ensure_ascii=False), encoding='utf-8')
    raise SystemExit(1 if changed else 0)


if __name__ == '__main__':
    main()
