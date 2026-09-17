"""Exercise source-row extraction and report safeguards without model calls."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.test_statement_matching import check_response, match_all, payable_rows, report
from scripts.compare_statement_strategies import signature, stage_timing


class FullStatementMatchingTests(unittest.TestCase):
    def test_parallel_timing_uses_wall_span(self):
        """Overlapping calls must not inflate elapsed time by summing their durations."""
        events = [{'id':key,'status':status,'at':f'2026-09-17T00:00:{second:02d}+00:00'}
                  for key,status,second in [('a','started',10),('b','started',15),
                                            ('a','finished',20),('b','finished',25)]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'usage.jsonl'
            path.write_text('\n'.join(json.dumps(event) for event in events),encoding='utf-8')
            result = stage_timing(path)
            self.assertEqual(result['wall_seconds'],15)
            self.assertEqual(sum(result['attempt_seconds']),20)
            self.assertEqual(result['unknown_duration_attempts'],0)

    def test_local_routing_requires_unique_bank_payment(self):
        """Repeated payments must not both receive the same deterministic payable row."""
        bank = {'id':'B1','amount':'150','currency':'MYR','direction':'out','date':'2025-12-01',
                'parties':['Alice Example'],'references':[]}
        item = {**bank,'id':'D1','source_cells':['D7','H7'],'expense_id':'','claim_group':''}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rows = match_all({'banks':[bank],'items':[item]},output,1,hybrid=True,local_only=True)
            self.assertEqual(rows[0]['assessment'],'strong')
            rows = match_all({'banks':[bank,{**bank,'id':'B2'}],'items':[item]},output,1,hybrid=True,local_only=True)
            self.assertTrue(all(row['assessment']=='tentative' for row in rows))
            self.assertFalse((output/'matching/token-usage.jsonl').exists())

    def test_source_cache_uses_allocation_not_wording(self):
        """Equivalent decimal amounts reuse checks; changed allocations never do."""
        row = {'bank_id':'B1','allocations':[{'item_id':'D1','amount':'10.00'}]}
        same = {**row,'reason':'different explanation','allocations':[{'item_id':'D1','amount':'10'}]}
        self.assertEqual(signature(row),signature(same))
        self.assertNotEqual(signature(row),signature({**same,'bank_id':'B2'}))

    def test_payee_rows_require_explicit_name_and_currency_columns(self):
        """Keep individual payables and their source cells without counting the total row."""
        text = '\n'.join([
            'D6={"value":"达人全名"} | H6={"value":"金额(RM)"}',
            'D7={"value":"Example Person"} | H7={"value":"RM150"}',
            'G8={"value":"总计"} | H8={"value":"150"}',
            'D9={"value":"cut',
        ])
        self.assertEqual(payable_rows(text), [{'party':'Example Person','amount':'150','cells':['D7','H7']}])
        self.assertEqual(payable_rows(text.replace('金额(RM)', 'Hours')), [])

    def test_response_must_cover_banks_and_reference_only_allowed_items(self):
        """A valid JSON shape cannot hide missing decisions or invented references."""
        row = {'bank_id':'B1','assessment':'strong','allocations':[{'item_id':'D1','amount':'10'}],'reason':''}
        with self.assertRaises(ValueError):
            check_response({'decisions':[row]}, ['B1','B2'], {'B1':['D1']})
        with self.assertRaises(ValueError):
            check_response({'decisions':[row]}, ['B1'], {'B1':['D2']})

    def test_competing_allocations_are_not_reported_as_strong(self):
        """Two batches cannot each spend the same full supporting amount."""
        facts = {'banks':[{'id':f'B{n}','amount':'25','currency':'MYR','direction':'out','date':'2025-12-01','parties':['Example']}
                          for n in (1,2)],
                 'items':[{'id':'D1','amount':'25','currency':'MYR','source_cells':[],
                           'document':'example','location':'page 1','boundary_unresolved':False}],
                 'source_documents':['example']}
        rows = [{'bank_id':f'B{n}','assessment':'strong','allocations':[{'item_id':'D1','amount':'25'}],'reason':'fixture'}
                for n in (1,2)]
        with tempfile.TemporaryDirectory() as directory:
            report(rows,facts,Path(directory))
            saved=json.loads((Path(directory)/'summary.json').read_text())
            self.assertEqual(saved['counts'],{'tentative':2})

    def test_repeated_page_totals_cannot_be_independent_capacity(self):
        """Unassembled multi-page evidence cannot independently support two full payments."""
        facts={'banks':[{'id':f'B{n}','amount':'25','currency':'MYR','direction':'out','date':'2025-12-01','parties':['Example']}
                        for n in (1,2)],
               'items':[{'id':f'D{n}','amount':'25','currency':'MYR','source_cells':[],
                         'document':'same-file','location':f'page {n}','boundary_unresolved':True} for n in (1,2)],
               'source_documents':['same-file']}
        rows=[{'bank_id':f'B{n}','assessment':'strong','allocations':[{'item_id':f'D{n}','amount':'25'}],'reason':'fixture'}
              for n in (1,2)]
        with tempfile.TemporaryDirectory() as directory:
            report(rows,facts,Path(directory))
            self.assertTrue(all(row['assessment']=='tentative' for row in rows))


if __name__ == '__main__':
    unittest.main()
