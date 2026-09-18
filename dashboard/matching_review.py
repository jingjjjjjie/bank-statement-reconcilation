"""Human review of frozen matching suggestions, with a separate persistent ledger."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path

from dashboard.review import write_json
from reconciliation.duplicate_workflow import fingerprint
from reconciliation.receipt_matching import amount, revision
from reconciliation.vision_workflow import removal_plan


WORKSPACE = Path(__file__).resolve().parent.parent
CACHE = WORKSPACE / 'duplicated/benchmarks/full-statement-240'


def read(path):
    """Read saved UTF-8 JSON without invoking a model."""
    return json.loads(path.read_text(encoding='utf-8'))


def money(value):
    """Return an explicit monetary value, leaving missing extraction facts unknown."""
    try:
        return amount(value)
    except (ValueError, TypeError):
        return None


def source_hash(path):
    """Treat changed or missing originals as stale evidence."""
    try:
        return fingerprint(Path(path))
    except OSError:
        return ''


def context(review):
    """Bind this project's ledger to the cached corpus and its original statement."""
    if review is None:
        raise ValueError('Choose a workspace before reviewing matches')
    index, facts = read(CACHE/'index.json'), read(CACHE/'facts.json')
    if Path(index['manifest']).resolve() != review.manifest_path.resolve():
        raise ValueError('The saved matching results belong to a different workspace')
    path = review.manifest_path.parent/'final-review/decisions.json'
    legacy_path = review.manifest_path.parent/'review/receipt-matches.json'
    if legacy_path.exists() and any(m.get('review_status')=='accepted' for m in read(legacy_path).get('matches',{}).values()):
        raise ValueError('Existing receipt-match approvals must be migrated or undone before using the cached final-review ledger')
    binding = revision([facts, index, read(CACHE/'decisions.json')])
    state = read(path) if path.exists() else {'binding':binding,'version':0,'decisions':{},'history':[]}
    if state['binding'] != binding:
        raise ValueError('Cached evidence changed. Keep the existing review and import a separate revision before continuing.')
    master = None
    for candidate in (WORKSPACE/'duplicated/projects').glob('*/bank-output/master_statement.csv'):
        if source_hash(candidate)==facts['bank_hash']:
            master = candidate
            break
    if master is None:
        raise ValueError('The original bank master for these cached results is unavailable')
    with master.open(encoding='utf-8-sig',newline='') as stream:
        bank_sources = {'B'+r['sequence']:r for r in csv.DictReader(stream)}
    live_path = review.manifest_path.parent/'review/state.json'
    excluded = set(removal_plan(read(live_path))) if live_path.exists() else set()
    banks = {b['id']:{**b,'source':bank_sources[b['id']]['source'],
                      'balance_checks':bank_sources[b['id']].get('balance_checks',''),
                      'page':int(bank_sources[b['id']]['page'])-1} for b in facts['banks']}
    items = {i['id']:{**i,'source_path':index['documents'][i['document']]['paths'][0],
                     'filename':Path(index['documents'][i['document']]['paths'][0]).name,
                     'excluded':i['document'] in excluded} for i in facts['items']}
    return path,state,banks,items,index,facts


def reservations(state, excluding=None):
    """Reserve approved allocations, even if their evidence later becomes stale."""
    used = {}
    for bank_id, decision in state['decisions'].items():
        if bank_id == excluding or decision['status'] != 'approved':
            continue
        for entry in decision['allocations']:
            if entry['amount']:
                used[entry['item_id']] = used.get(entry['item_id'],Decimal(0))+amount(entry['amount'])
    return used


def pairing_confidence(bank, suggestion, items, decision, stale):
    """Label saved pairing evidence without converting confidence into approval."""
    allocations = suggestion.get('allocations', [])
    suggested = {a['item_id']: money(a['amount']) for a in allocations}
    chosen = {a['item_id']: money(a['amount']) for a in decision['allocations']} if decision else {}
    if chosen and chosen != suggested:
        return {'level': 'low', 'reason': 'Supporting selection changed; the saved confidence does not assess this pairing.'}
    if not allocations:
        return {'level': None, 'reason': 'No proposed supporting match.'}
    if stale or any(a['item_id'] not in items or items[a['item_id']]['stale'] or
                    items[a['item_id']]['excluded'] for a in allocations):
        return {'level': 'low', 'reason': 'Supporting evidence changed, is unavailable, or is excluded.'}
    values = [money(a['amount']) for a in allocations]
    if any(value is None for value in values) or sum(values, Decimal(0)) != money(bank['amount']):
        return {'level': 'low', 'reason': 'The proposed allocations do not fully explain the bank amount.'}
    if any(items[a['item_id']].get('boundary_unresolved') for a in allocations):
        return {'level': 'low', 'reason': 'Receipt boundaries still need checking against the original document.'}
    level = 'high' if suggestion.get('assessment') == 'strong' else 'low'
    return {'level': level, 'reason': suggestion.get('reason') or 'The saved pairing needs checking against the original evidence.'}


def snapshot(review):
    """Expose suggestions, human outcomes, remaining evidence and changed-source flags."""
    path,state,banks,items,index,facts = context(review)
    hashes = {digest:source_hash(doc['paths'][0]) for digest,doc in index['documents'].items()}
    bank_hashes = {bank['source']:source_hash(bank['source']) for bank in banks.values()}
    choices = {}
    for stage in ('matching','contextual'):
        for payload in (CACHE/stage).glob('input-*.json'):
            for bank in read(payload)['banks']:
                choices.setdefault(bank['id'],[]).extend(bank['candidate_ids'])
    suggestions = {r['bank_id']:r for r in read(CACHE/'decisions.json')}
    used = reservations(state)
    for key,item in items.items():
        total = money(item['amount'])
        item.update(stale=hashes[item['document']]!=item['document'],
                    used=str(used.get(key,Decimal(0))),
                    remaining=str(total-used.get(key,Decimal(0))) if total is not None else '')
    for key,bank in banks.items():
        suggestion = suggestions[key]
        decision = state['decisions'].get(key)
        stale = bank_hashes[bank['source']] != facts['statement_hash']
        if decision:
            stale = stale or any(items[a['item_id']]['stale'] or items[a['item_id']]['excluded'] for a in decision['allocations'])
        status = decision['status'] if decision else 'pending'
        support = bool(decision and status=='approved' and not stale and decision['difference']=='0' and not decision['context_only'])
        bank.update(suggestion=suggestion,candidates=list(dict.fromkeys([a['item_id'] for a in suggestion['allocations']]+choices.get(key,[]))),
                    decision=decision,review_status=status,stale=stale,
                    confidence=pairing_confidence(bank,suggestion,items,decision,stale),
                    support_status='Supporting' if support else 'No supporting',
                    history=[h for h in state['history'] if h['bank_id']==key])
    return {'binding':state['binding'],'version':state['version'],'banks':list(banks.values()),
            'items':list(items.values()),'workspace':review.root.parent.name,
            'source':'Saved 20-line matching results','assembly_incomplete':not facts.get('assembly_count')}


def decide(review, body):
    """Validate and atomically save an explicit approval, denial or undo with history."""
    path,state,banks,items,index,facts = context(review)
    if body.get('binding')!=state['binding'] or body.get('version')!=state['version']:
        raise ValueError('Another decision was saved. Refresh before submitting this change.')
    bank_id,action = body.get('bank_id'),body.get('action')
    if bank_id not in banks or action not in {'approve','deny','undo'}:
        raise ValueError('Choose a valid transaction and action')
    reviewer = str(body.get('reviewer') or 'Local user').strip() or 'Local user'
    note = str(body.get('note','')).strip()
    if len(reviewer)>120 or len(note)>4000:
        raise ValueError('Keep the review note under 4,000 characters')
    bank = banks[bank_id]
    before = state['decisions'].get(bank_id)
    allocations,flags = [],[]
    total = Decimal(0)
    if action=='approve':
        if bank['balance_checks']!='passed':
            raise ValueError('The bank master must pass balance validation before approving matches')
        if source_hash(bank['source'])!=facts['statement_hash']:
            raise ValueError('The bank statement changed or is unavailable')
        selected = body.get('allocations')
        if not isinstance(selected,list) or not 1<=len(selected)<=50:
            raise ValueError('Select at least one supporting item')
        used,seen,documents = reservations(state,bank_id),set(),{}
        for entry in selected:
            key = entry.get('item_id')
            if key not in items or key in seen:
                raise ValueError('Unknown or repeated supporting item')
            seen.add(key)
            item = items[key]
            if item['excluded'] or source_hash(item['source_path'])!=item['document']:
                raise ValueError('A selected document was excluded, changed or is unavailable')
            value = entry.get('amount','')
            capacity = money(item['amount'])
            if value:
                value = amount(value)
                if capacity is None or not item['currency'] or item['currency']!=bank['currency']:
                    raise ValueError('Unknown or different currencies/amounts can only be linked as contextual evidence with no allocation')
                if value<=0 or value>capacity-used.get(key,Decimal(0)):
                    raise ValueError(f'{key}: allocation exceeds the available supporting amount')
                if value < capacity:
                    flags.append(f'{key}: source {capacity}, allocated here {value}, source difference {capacity-value}')
                total += value
            else:
                flags.append(f'{key}: contextual evidence without a monetary allocation')
            documents.setdefault(item['document'],[]).append(item)
            if item['boundary_unresolved']:
                flags.append(f'{key}: receipt boundaries require human verification')
            allocations.append({'item_id':key,'amount':str(value) if value else '',
                                'document':item['document'],'source_path':item['source_path'],
                                'location':item['location'],'source_amount':item['amount'],'currency':item['currency'],
                                'source_difference':str(capacity-value) if capacity is not None and value else ''})
        # A page total cannot silently become a second expense or capacity pool.
        for digest,selected_items in documents.items():
            if len(selected_items)>1 and any(i['boundary_unresolved'] for i in selected_items):
                raise ValueError('Select one monetary item from this unassembled document; repeated page totals cannot be added')
            for other_id,decision in state['decisions'].items():
                if other_id==bank_id or decision['status']!='approved':
                    continue
                for previous in decision['allocations']:
                    if (previous['document']==digest and previous['item_id'] not in seen and previous['amount']
                            and (items[previous['item_id']]['boundary_unresolved'] or any(i['boundary_unresolved'] for i in selected_items))):
                        raise ValueError('Another payment uses a different page of this unassembled document; undo that allocation or resolve the receipt boundaries first')
        if total>amount(bank['amount']):
            raise ValueError('Total allocation exceeds the bank payment. Adjust the selected amounts.')
        difference = amount(bank['amount'])-total
        if difference:
            flags.append(f'Unallocated bank amount: {difference}')
        if len(allocations)>1:
            flags.append('Multiple supporting items: verify these are distinct expenses, not duplicate evidence')
        if flags and (not note or body.get('acknowledged') is not True):
            raise ValueError('Add a review note and confirm the flagged differences or evidence limitations')
        after = {'status':'approved','allocations':allocations,'allocated_total':str(total),
                 'difference':format(difference.normalize(),'f'),'context_only':total==0,'flags':flags,
                 'reviewer':reviewer,'note':note}
    elif action=='deny':
        after = {'status':'denied','allocations':[],'difference':bank['amount'],
                 'context_only':False,'reviewer':reviewer,'note':note,'flags':[]}
    else:
        if not before:
            raise ValueError('There is no saved decision to undo')
        after = None
    at = datetime.now(timezone.utc).isoformat()
    if after:
        after['at'] = at
        state['decisions'][bank_id] = after
    else:
        state['decisions'].pop(bank_id,None)
    state['history'].append({'bank_id':bank_id,'transaction_id':bank['transaction_id'],'action':action,
                             'reviewer':reviewer,'at':at,'note':note,'before':before,'after':after})
    state['version'] += 1
    path.parent.mkdir(parents=True,exist_ok=True)
    write_json(path,state)
    return {'saved':True,'version':state['version']}


def evidence(review, kind, key):
    """Resolve only corpus-listed originals and verify their bytes before previewing."""
    _,_,banks,items,_,facts = context(review)
    if kind=='bank':
        source,expected = banks[key]['source'],facts['statement_hash']
    elif kind=='item':
        source,expected = items[key]['source_path'],items[key]['document']
    else:
        raise ValueError('Unknown evidence type')
    if source_hash(source)!=expected:
        raise ValueError('Original evidence changed or is unavailable')
    return Path(source)


def export_csv(review):
    """Export every bank row with human status, discrepancies and source references."""
    data = snapshot(review)
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['Bank ID','Transaction ID','Date','Party','Direction','Currency','Bank amount','Support status',
                     'Review status','Stale evidence','Allocated amount','Difference','Evidence','Flags','Reviewer','Notes'])
    for bank in data['banks']:
        decision = bank['decision'] or {}
        values = [bank['id'],bank['transaction_id'],bank['date'],' / '.join(bank['parties']),bank['direction'],
                  bank['currency'],bank['amount'],bank['support_status'],bank['review_status'],str(bank['stale']),
                  decision.get('allocated_total','0'),decision.get('difference',bank['amount']),
                  json.dumps(decision.get('allocations',[]),ensure_ascii=False),' | '.join(decision.get('flags',[])),decision.get('reviewer',''),decision.get('note','')]
        writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for v in values])
    return ('\ufeff'+stream.getvalue()).encode('utf-8')
