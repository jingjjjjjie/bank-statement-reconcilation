"""Exercise the final human ledger without model calls or real customer decisions."""
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dashboard import matching_review as matching
from reconciliation.duplicate_workflow import fingerprint


class MatchingReviewTests(unittest.TestCase):
    def setUp(self):
        """Build an isolated cache, bank master and original evidence corpus."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root/'duplicated/projects/test'
        self.project.mkdir(parents=True)
        self.cache = self.root/'cache'
        self.cache.mkdir()
        self.review = SimpleNamespace(manifest_path=self.project/'manifest.json',root=self.root/'uploads/documents',data=self.project/'data')
        self.review.root.mkdir(parents=True)
        original = self.root/'statement.txt'
        original.write_text('Original statement',encoding='utf-8')
        master = self.project/'bank-output/master_statement.csv'
        master.parent.mkdir()
        with master.open('w',encoding='utf-8',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=['sequence','source','page','balance_checks'])
            writer.writeheader()
            writer.writerows({'sequence':n,'source':str(original),'page':1,'balance_checks':'passed'} for n in (1,2,3))
        documents = {}
        for n in (1,2):
            source = self.review.root/f'receipt-{n}.txt'
            source.write_text(f'Original receipt {n} amount 10',encoding='utf-8')
            documents[fingerprint(source)] = {'paths':[str(source)],'units':[{'label':'Page 1','text':source.read_text()}]}
        digests = list(documents)
        banks = [{'id':f'B{n}','transaction_id':f'tx-{n}','amount':'10' if n<3 else '5','currency':'MYR','direction':'out',
                  'date':'2025-12-01','parties':[f'Person {n}'],'description':'Payment','references':[]} for n in (1,2,3)]
        items = [{'id':f'D{n}','document':digests[n-1],'amount':'10','currency':'MYR','parties':[f'Person {n}'],
                  'description':'Receipt','location':'Page 1','unit':0,'source_cells':[],'boundary_unresolved':False} for n in (1,2)]
        items.append({**items[1],'id':'E1','amount':'','currency':''})
        self.write(self.cache/'facts.json',{'banks':banks,'items':items,'statement_hash':fingerprint(original),
                                         'bank_hash':fingerprint(master),'assembly_count':1})
        self.write(self.cache/'index.json',{'manifest':str(self.review.manifest_path),'documents':documents})
        self.write(self.cache/'decisions.json',[{'bank_id':f'B{n}','assessment':'tentative','allocations':[{'item_id':'D1','amount':'10'}],
                                               'reason':'Possible supporting document'} for n in (1,2,3)])
        self.addCleanup(patch.stopall)
        patch.object(matching,'WORKSPACE',self.root).start()
        patch.object(matching,'CACHE',self.cache).start()

    def write(self, path, data):
        """Write fixture JSON to an isolated location."""
        path.write_text(json.dumps(data),encoding='utf-8')

    def test_trash_document_cannot_be_approved_as_support(self):
        """Final review respects explicit document trash classifications."""
        item = matching.context(self.review)[3]['D1']
        folder = self.project / 'review'
        folder.mkdir()
        self.write(folder / 'receipt-matches.json', {'matches': {}, 'trash': {item['document']: {'classification': 'trash'}}})
        data = matching.snapshot(self.review)
        self.assertTrue(next(entry for entry in data['items'] if entry['id'] == 'D1')['excluded'])
        with self.assertRaisesRegex(ValueError, 'excluded'):
            matching.decide(self.review, self.request())

    def request(self, bank='B1', action='approve', allocations=None, **extra):
        """Build a request bound to the current persisted revision."""
        state = matching.context(self.review)[1]
        return {'bank_id':bank,'action':action,'binding':state['binding'],'version':state['version'],
                'allocations':allocations if allocations is not None else [{'item_id':'D1','amount':'10'}],
                'reviewer':'Test reviewer','note':'Checked originals','acknowledged':True,**extra}

    def test_confidence_is_separate_from_approval_and_downgrades_stale_evidence(self):
        """High never approves a pairing; missing or changed support is not high confidence."""
        suggestions = matching.read(self.cache/'decisions.json')
        suggestions[0]['assessment'] = 'strong'
        suggestions[2]['allocations'] = []
        self.write(self.cache/'decisions.json', suggestions)
        data = matching.snapshot(self.review)
        self.assertEqual([b['confidence']['level'] for b in data['banks']], ['high', 'low', None])
        self.assertTrue(all(b['review_status'] == 'pending' for b in data['banks']))
        self.assertTrue(all(b['support_status'] == 'No supporting' for b in data['banks']))
        matching.decide(self.review, self.request())
        self.assertEqual(matching.snapshot(self.review)['banks'][0]['confidence']['level'], 'high')
        (self.review.root/'receipt-1.txt').write_text('Changed evidence')
        self.assertEqual(matching.snapshot(self.review)['banks'][0]['confidence']['level'], 'low')

    def test_high_confidence_requires_full_amount_and_current_selection(self):
        """Amount gaps and manually changed pairings cannot inherit a high label."""
        suggestions = matching.read(self.cache/'decisions.json')
        suggestions[0]['assessment'] = 'strong'
        suggestions[0]['allocations'][0]['amount'] = '5'
        self.write(self.cache/'decisions.json', suggestions)
        self.assertEqual(matching.snapshot(self.review)['banks'][0]['confidence']['level'], 'low')
        matching.decide(self.review, self.request(allocations=[{'item_id':'D2','amount':'10'}]))
        self.assertIn('selection changed', matching.snapshot(self.review)['banks'][0]['confidence']['reason'])

    def test_evidence_explanations_do_not_turn_amounts_into_matches(self):
        """Explain name/currency gaps and stale evidence without changing decisions."""
        bank = {'parties': ['Nur Fajrina'], 'amount': '150', 'currency': 'MYR'}
        item = {'parties': [' nur   FAJRINA '], 'amount': '150.00', 'currency': 'MYR'}
        self.assertIn('Same extracted party name and amount', matching.evidence_reason(bank, item))
        self.assertIn('Amount alone', matching.evidence_reason(bank, {**item, 'parties': ['Siti']}))
        self.assertIn('differs or is unknown', matching.evidence_reason(bank, {**item, 'currency': 'USD'}))
        self.assertIn('differs or is unknown', matching.evidence_reason(bank, {**item, 'amount': ''}))
        self.assertIn('Unavailable', matching.evidence_reason(bank, {**item, 'stale': True}))
        self.assertIn('No exact', matching.evidence_reason(bank, {**item, 'parties': [], 'amount': ''}))
        before = matching.context(self.review)[1]
        snapshot = matching.snapshot(self.review)
        self.assertIn('Same extracted', snapshot['banks'][0]['evidence_reasons']['D1'])
        self.assertEqual(before, matching.context(self.review)[1])

    def test_approval_persists_and_undo_releases_capacity(self):
        """Only an explicit approval changes support; undo retains history and frees amounts."""
        self.assertTrue(all(b['support_status']=='No supporting' for b in matching.snapshot(self.review)['banks']))
        matching.decide(self.review,self.request())
        data = matching.snapshot(self.review)
        self.assertEqual(data['banks'][0]['support_status'],'Supporting')
        self.assertEqual(data['items'][0]['remaining'],'0')
        with self.assertRaisesRegex(ValueError,'exceeds'):
            matching.decide(self.review,self.request('B2'))
        matching.decide(self.review,self.request(action='undo'))
        data = matching.snapshot(self.review)
        self.assertEqual(data['banks'][0]['review_status'],'pending')
        self.assertEqual(len(data['banks'][0]['history']),2)
        self.assertEqual(data['items'][0]['remaining'],'10')

    def test_stale_tab_and_unknown_items_are_rejected(self):
        """Concurrent tabs cannot overwrite a newer decision or submit invented evidence."""
        stale = self.request('B2')
        matching.decide(self.review,self.request(action='deny'))
        with self.assertRaisesRegex(ValueError,'Another decision'):
            matching.decide(self.review,stale)
        with self.assertRaisesRegex(ValueError,'Unknown'):
            matching.decide(self.review,self.request(allocations=[{'item_id':'fake','amount':'10'}]))

    def test_partial_and_contextual_support_stay_flagged(self):
        """A human approval cannot hide missing or partially allocated monetary evidence."""
        with self.assertRaisesRegex(ValueError,'confirm'):
            matching.decide(self.review,self.request(allocations=[{'item_id':'D1','amount':'5'}],acknowledged=False))
        matching.decide(self.review,self.request(allocations=[{'item_id':'D1','amount':'5'}]))
        data = matching.snapshot(self.review)
        self.assertEqual(data['banks'][0]['decision']['difference'],'5')
        self.assertEqual(data['banks'][0]['support_status'],'No supporting')
        matching.decide(self.review,self.request('B2',allocations=[{'item_id':'E1','amount':''}]))
        self.assertTrue(matching.snapshot(self.review)['banks'][1]['decision']['context_only'])
        with self.assertRaisesRegex(ValueError,'Unknown or different'):
            matching.decide(self.review,self.request('B2',allocations=[{'item_id':'E1','amount':'10'}]))

    def test_split_payments_share_capacity_without_double_spending(self):
        """A partially used receipt can support another payment up to its remaining amount."""
        matching.decide(self.review,self.request(allocations=[{'item_id':'D1','amount':'5'}]))
        matching.decide(self.review,self.request('B3',allocations=[{'item_id':'D1','amount':'5'}]))
        self.assertEqual(matching.snapshot(self.review)['items'][0]['remaining'],'0')

    def test_changed_source_stays_reserved_but_not_supported(self):
        """Changed originals revoke displayed support without silently freeing their allocations."""
        matching.decide(self.review,self.request())
        source = matching.evidence(self.review,'item','D1')
        source.write_text('Changed original',encoding='utf-8')
        data = matching.snapshot(self.review)
        self.assertTrue(data['banks'][0]['stale'])
        self.assertEqual(data['banks'][0]['support_status'],'No supporting')
        self.assertEqual(data['items'][0]['remaining'],'0')
        with self.assertRaisesRegex(ValueError,'changed'):
            matching.evidence(self.review,'item','D1')

    def test_denial_and_export_include_every_transaction(self):
        """Denied suggestions remain separate from originals and export with unreviewed rows."""
        matching.decide(self.review,self.request(action='deny',note='=not a formula'))
        exported = matching.export_csv(self.review).decode('utf-8-sig')
        self.assertIn('denied',exported)
        self.assertIn("'=not a formula",exported)
        self.assertEqual(len(list(csv.DictReader(exported.splitlines()))),3)

    def test_cache_changes_and_workspace_changes_do_not_reuse_approvals(self):
        """The ledger is tied to one exact cache and workspace, not reusable sequence IDs."""
        matching.decide(self.review,self.request())
        facts = matching.read(self.cache/'facts.json')
        facts['items'][0]['amount'] = '20'
        self.write(self.cache/'facts.json',facts)
        with self.assertRaisesRegex(ValueError,'Cached evidence changed'):
            matching.context(self.review)
        self.review.manifest_path = self.root/'another-manifest.json'
        with self.assertRaisesRegex(ValueError,'different workspace'):
            matching.context(self.review)

    def test_unassembled_pages_cannot_create_new_capacity(self):
        """Switching page IDs cannot bypass a reservation on the same unfinished receipt."""
        facts = matching.read(self.cache/'facts.json')
        facts['items'][0]['boundary_unresolved'] = True
        facts['items'].append({**facts['items'][0],'id':'D4','unit':1})
        self.write(self.cache/'facts.json',facts)
        matching.decide(self.review,self.request(allocations=[{'item_id':'D1','amount':'5'}]))
        with self.assertRaisesRegex(ValueError,'different page'):
            matching.decide(self.review,self.request('B3',allocations=[{'item_id':'D4','amount':'5'}]))

    def test_legacy_approvals_cannot_be_ignored(self):
        """The cached ledger refuses to double-reserve evidence accepted by the old flow."""
        path = self.project/'review/receipt-matches.json'
        path.parent.mkdir()
        self.write(path,{'matches':{'old':{'review_status':'accepted'}}})
        with self.assertRaisesRegex(ValueError,'migrated or undone'):
            matching.context(self.review)


if __name__=='__main__':
    unittest.main()
