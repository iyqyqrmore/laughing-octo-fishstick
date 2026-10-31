"""Frozen native-cycle observations, shared budgets, real Tk and safe exports."""
from copy import deepcopy
from tempfile import TemporaryDirectory
from unittest.mock import patch
import threading
import unittest

from coincat_eth_evaluator import evaluate_cycle, public_cycle_report
from coincat_v80_discovery import select_books
from coincat_working_allocation import AllocationRow
from coincat_simple_diagnostics import make_report
from offline_tests import test_v91_scanner_gui as fixtures
from offline_tests.test_v92_eth_evaluator import inputs, NOW


def prepare(folder):
    ledger,client,scanner=fixtures.setup(folder)
    data=inputs();client.q=data['quotes'];client.rules=data['rules']
    scanner.catalog=list(data['catalog']);scanner.rules=deepcopy(data['rules'])
    scanner.catalog_at=NOW;scanner.account_at=NOW;scanner.balances={'ETH':data['starting_eth']}
    scanner.fees.refresh_from_client(client,now=NOW)
    return ledger,client,scanner


def run(scanner,client,**kwargs):
    return scanner.scan(now=NOW,collect=fixtures.collector(client),
                        allocation_draft=(AllocationRow('ETH',inputs()['starting_eth']),),**kwargs)


class CycleIntegration(unittest.TestCase):
    def test_one_collection_native_funnel_and_no_financial_writes(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=prepare(folder);before=fixtures.ledger_dump(ledger)
            r=run(s,client);c=r['eth_cycle_research']
            self.assertEqual(c['funnel'],dict(discovered=2,observed=2,validated=2,costed=1,positive=1,execution_evidence=0))
            self.assertEqual(c['scheduling']['requested_books'],3)
            self.assertLessEqual(r['quote_scheduling']['requested_books'],16)
            self.assertFalse(c['execution_eligible']);self.assertEqual(before,fixtures.ledger_dump(ledger))
            frozen=deepcopy(c);client.q.clear();s.rules.clear();s.balances['ETH']=0
            self.assertEqual(c,frozen)

    def test_previous_scan_cache_cannot_fill_missing_cycle_dependency(self):
        with TemporaryDirectory() as folder:
            _,client,s=prepare(folder);run(s,client)
            def partial(pairs,**kwargs):
                q,e,t=fixtures.collector(client)(pairs,**kwargs);q.pop('AA-BB',None)
                return q,{'AA-BB':'TEST_MISSING'},t
            r=s.scan(now=NOW,collect=partial,allocation_draft=(AllocationRow('ETH',inputs()['starting_eth']),))
            c=r['eth_cycle_research']
            self.assertEqual(c['funnel']['observed'],0);self.assertEqual(c['funnel']['costed'],0)
            self.assertTrue(all('QUOTE_UNOBSERVED:AA-BB' in row['blockers'] for row in c['results']))

    def test_stop_during_evaluation_does_not_commit_results_or_counters(self):
        with TemporaryDirectory() as folder:
            _,client,s=prepare(folder);cancel=threading.Event()
            def stop(**kwargs):
                cancel.set();return evaluate_cycle(**kwargs)
            with patch('coincat_eth_evaluator.evaluate_cycle',side_effect=stop):
                r=run(s,client,cancel=cancel)
            self.assertEqual(r['state'],'CANCELLED');self.assertIsNone(s.last_result)
            self.assertEqual(s.sequence,0);self.assertEqual(s.cycle_cursor,0)
            self.assertEqual(s.lab.counts,{});self.assertEqual(s.books,{})

    def test_cycle_and_endpoint_groups_share_six_book_limit(self):
        data=inputs();rules=data['rules'];catalog=list(data['catalog'])
        for i in range(4):
            p=f'X{i}-USD';rules[p]=dict(next(iter(rules.values())),product_id=p);catalog.append(p)
        due=[dict(books=tuple(catalog[-4:]),earliest=NOW,deadline=NOW+20,jobs=())]
        plan=select_books(catalog,rules,{'ETH'},quotes={},now=NOW,priority_groups=due,
            cycle_groups=[dict(books=tuple(data['catalog']),index=0)])
        self.assertEqual(plan['endpoint_requests'],4);self.assertIsNone(plan['_cycle_group'])
        self.assertEqual(plan['cycle_requests'],0);self.assertLessEqual(len(plan['books']),16)


class CycleGUI(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def test_tab_native_advantage_funnel_export_and_queued_stop_result(self):
        _,client,s=prepare(self.temp.name)
        self.app.scanner=s;self.app.connected=True
        result=run(s,client)
        self.app.last_result=result;self.app._render(result);self.root.update_idletasks()
        self.assertEqual(len(self.app.cycle_tree.get_children()),2)
        self.assertIn('positive: 1',self.app.cycle_summary.get())
        exported=make_report(self.app,now=NOW)
        self.assertIn('SECTION COMPLETENESS: COMPLETE (8/8)',exported)
        self.assertIn('NATIVE_ETH_CYCLE_RESEARCH_NOT_REALIZED_INCOME',exported)
        public=public_cycle_report(result['eth_cycle_research'])
        self.assertNotIn('receipts',str(public));self.assertNotIn('net_additional_eth',str(public))
        rows=[self.app.cycle_tree.item(i)['values'] for i in self.app.cycle_tree.get_children()]
        self.app._stop();self.app.jobs.put(('scan',self.app.generation-1,dict(result,eth_cycle_research={}),None))
        self.app._poll()
        self.assertIs(self.app.last_result,result)
        self.assertEqual(rows,[self.app.cycle_tree.item(i)['values'] for i in self.app.cycle_tree.get_children()])
