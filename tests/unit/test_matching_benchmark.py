"""Test retrieval coverage and deterministic monetary checks used in experiments."""
import unittest

from scripts.benchmark_matching import build_candidates, fastlane, guard_allocations, shortlist, specific_name
from scripts.matching_cases import make_cases


class MatchingExperimentTests(unittest.TestCase):
    def setUp(self):
        """Prepare independent labelled facts without any model calls."""
        self.data = make_cases()
        self.pool, self.ranked, _ = build_candidates(self.data["banks"], self.data["documents"], specific=True)

    def test_group_is_one_candidate_and_ties_expand(self):
        """Seven related claims fit in one candidate; equally plausible options remain visible."""
        selected = shortlist(self.ranked['S0-Bgroup-seven'], '5')
        self.assertEqual(len(self.pool[selected[0][1]]['document_ids']), 7)
        tied = self.ranked['S0-Bseven-tied']
        self.assertEqual(len(shortlist(tied, '5')), 5)
        self.assertEqual(len(shortlist(tied, 'adaptive')), 7)

    def test_full_name_matching_ignores_honorifics_not_identity(self):
        """Common name fragments must not swamp candidate ranking."""
        self.assertTrue(specific_name(['CIK LIM SHU EN'], ['Lim Shu En']))
        self.assertTrue(specific_name(['WU WENJUN'], ['Wenjun Wu']))
        self.assertFalse(specific_name(['NURUL AIN NORDIN'], ['NURUL FATIMAH AZANAN']))

    def test_claim_amount_survives_unrelated_same_recipient_documents(self):
        """Keep a merchant receipt in view without assuming who claimed the expense."""
        bank = {'id': 'claim', 'amount': '250.00', 'currency': 'MYR', 'direction': 'out',
                'parties': ['WU WENJUN'], 'references': ['Canva'],
                'description': 'Canva zuotufei'}
        receipt = {'id': 'canva', 'amount': '250.00', 'currency': 'MYR', 'direction': '',
                   'parties': ['Canva Pty Ltd'], 'references': [],
                   'description': 'Canva Pro subscription'}
        documents = [receipt] + [{**receipt, 'id': f'travel-{n}', 'amount': str(50 + n),
                                 'parties': ['WU WENJUN'], 'description': 'Travel receipt'}
                                for n in range(6)]
        documents += [{**receipt, 'id': 'wrong-currency', 'currency': 'USD'},
                      {**receipt, 'id': 'wrong-direction', 'direction': 'in'}]
        pool, ranked, _ = build_candidates([bank], documents, grouped=False, specific=True)
        choices = {'claim': shortlist(ranked['claim'], 'adaptive')}
        self.assertEqual(choices['claim'][0][1], 'canva')
        self.assertFalse({'wrong-currency', 'wrong-direction'} & {key for _, key in choices['claim']})
        self.assertEqual(fastlane([bank], pool, choices), [])

    def test_truncated_bank_name_keeps_recipient_in_shortlist(self):
        """Anchored truncation beats amount-only ties but never establishes approval."""
        from reconciliation.candidates import truncated_name
        bank = {'id': 'payment', 'amount': '90', 'currency': 'MYR', 'direction': 'out',
                'parties': ['SAFINAH BINTI ABDULL'], 'references': []}
        row = {'id': 'z-recipient', 'amount': '90', 'currency': 'MYR', 'direction': '',
               'parties': ['Safinah binti Abdullah'], 'references': []}
        others = [{**row, 'id': f'a-{n}', 'parties': ['Another recipient']} for n in range(15)]
        _, ranked, _ = build_candidates([bank], others + [row], grouped=False, specific=True)
        self.assertEqual(shortlist(ranked['payment'], 'adaptive')[0][1], 'z-recipient')
        self.assertFalse(specific_name(bank['parties'], row['parties']))
        self.assertFalse(truncated_name(['NURUL BINTI ABDULL'], row['parties']))
        self.assertFalse(truncated_name(['SAFINAH BINTI AB'], row['parties']))

    def test_competing_claims_are_globally_flagged_but_instalments_survive(self):
        """Global arithmetic catches cross-batch reuse while allowing explicit partial payments."""
        rows = [{'bank_id': 'S0-B' + tag, 'status': 'proposal', 'candidate_ids': ['S0-' + candidate], 'reason': ''}
                for tag, candidate in [('competing-one', 'contested'), ('competing-two', 'contested'),
                                       ('instalment-one', 'instalment'), ('instalment-two', 'instalment')]]
        result = guard_allocations(rows, self.data['banks'], self.pool)
        self.assertEqual([r['status'] for r in result], ['review', 'review', 'proposal', 'proposal'])

    def test_original_invoice_and_confirmation_count_once(self):
        """Two supporting files describe one economic expense, not twice its amount."""
        c = self.pool['S0-invoice']
        self.assertEqual(set(c['document_ids']), {'S0-invoice', 'S0-confirmation'})
        self.assertEqual(c['amount'], '104')

    def test_existing_allocations_are_reserved(self):
        """A previously accepted partial payment reduces capacity for new proposals."""
        row = {'bank_id': 'S0-Binstalment-two', 'status': 'proposal',
               'candidate_ids': ['S0-instalment'], 'reason': ''}
        result = guard_allocations([row], self.data['banks'], self.pool, {'S0-instalment': '50'})
        self.assertEqual(result[0]['status'], 'review')

    def test_local_routing_does_not_invent_matches(self):
        """Every model-free proposal agrees with the fixture's independent expected evidence."""
        choices = {k:shortlist(v, 'adaptive') for k,v in self.ranked.items()}
        decisions = fastlane(self.data['banks'], self.pool, choices)
        self.assertEqual(len(decisions), 24)
        for row in decisions:
            expected = self.data['truth'][row['bank_id']]
            self.assertEqual(row['status'], expected['status'])
            if row['status'] == 'proposal':
                documents = {d for c in row['candidate_ids'] for d in self.pool[c]['document_ids']}
                self.assertEqual(documents, set(expected['documents']))

    def test_control_total_is_not_unrestricted_payment_capacity(self):
        """A schedule total cannot substantiate an unspecified individual payee allocation."""
        self.pool['S0-instalment']['amount_role'] = 'control_total'
        row = {'bank_id': 'S0-Binstalment-one', 'status': 'proposal',
               'candidate_ids': ['S0-instalment'], 'reason': ''}
        result = guard_allocations([row], self.data['banks'], self.pool)
        self.assertEqual(result[0]['status'], 'review')


if __name__ == '__main__':
    unittest.main()
