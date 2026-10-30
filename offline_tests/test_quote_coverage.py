"""Synthetic coverage/deadline regressions; no exchange or private records."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock,patch
import threading,unittest

from coincat_v80_discovery import select_books,book_status,listed_usd_paths
from coincat_v701_quotes import mark_paths
from coincat_v701_transport import QuoteSnapshot,GetBudget,QuoteDeferred
from coincat_passive_lab import PassiveLab
from coincat_settings_advisor import settings_advice
from coincat_scanner import Scanner
from offline_tests.test_v91_full_balance import market,scan,NOW
from offline_tests import test_v91_scanner_gui as gui


def broad_market(count):
    pairs=[f'C{i:04d}-USD' for i in range(count)]
    q={p:(D(100),D('100.01'),NOW) for p in pairs}
    rules={p:dict(product_id=p,product_type='SPOT',status='online',base_increment='.00000001',
        base_min_size='.00000001',quote_min_size='.00000001',quote_increment='.00000001') for p in pairs}
    return q,rules


class BroadClient(gui.FakeClient):
    def __init__(self,count=40):
        self.q,self.rules=broad_market(count);self.calls=[]
    def get_accounts(self,**kwargs):
        self.calls.append('accounts')
        return {'accounts':[{'currency':'USD','available_balance':{'value':'1000'},'hold':{'value':'0'}}],
                'has_next':False}
    def get_products(self,*,limit=250,offset=0,**kwargs):
        self.calls.append('products')
        return {'products':list(self.rules.values())[offset:offset+limit]}


def broad_scanner(folder,count=40):
    ledger,old,s=gui.setup(folder)
    client=BroadClient(count)
    s=Scanner(ledger,client,s.fees,s.market_store)
    s.refresh(now=NOW)
    return ledger,client,s


class QuotePlanning(unittest.TestCase):
    def test_fills_sixteen_request_slots_instead_of_three_direction_ceiling(self):
        q,rules=broad_market(40)
        args=dict(catalog=list(q),rules=rules,funding={'USD'},quotes={},now=NOW)
        before=select_books(**args,max_routes=3)
        after=select_books(**args)
        self.assertEqual(len(before['directions']),3)
        self.assertEqual(len(after['directions']),16)
        self.assertEqual(len(after['books']),16)
        self.assertEqual(len(set(after['books'])),16)
        self.assertEqual(len(select_books(**args,limit=1000)['books']),16)
        self.assertEqual(select_books(**args,limit=0)['books'],[])

    def test_recent_dependencies_reused_but_old_wide_future_books_refetched(self):
        q,rules=market()
        args=dict(catalog=list(q),rules=rules,funding={'BTC'},now=NOW)
        reuse=select_books(**args,quotes=q)
        self.assertEqual(reuse['books'],[])
        self.assertEqual(len(reuse['directions']),2)
        for stamp in (NOW-7,NOW+1):
            quotes={p:(b[0],b[1],stamp) for p,b in q.items()}
            plan=select_books(**args,quotes=quotes)
            self.assertEqual(set(plan['books']),set(q))
        q['BTC-USD']=(D(50000),D(60000),NOW)
        self.assertIn('BTC-USD',select_books(**args,quotes=q)['books'])

    def test_complete_shared_dependencies_and_both_sides_deduplicate_gets(self):
        q,rules=market()
        plan=select_books(list(q),rules,{'BTC','ETH','USD'},quotes={},now=NOW)
        self.assertEqual(set(plan['books']),set(q))
        self.assertEqual(len(plan['books']),3)
        self.assertEqual(len(plan['directions']),6)
        for pair,side,source,target in plan['directions']:
            self.assertIn(pair,plan['books'])

    def test_direct_marks_and_structural_paths_preserve_shortest_non_circular_policy(self):
        q,rules=market()
        for asset,path in listed_usd_paths(q).items():
            self.assertEqual(path,mark_paths(asset,set(q)))
        del q['ETH-USD'];del rules['ETH-USD']
        plan=select_books(list(q),rules,{'BTC'},quotes={},now=NOW)
        self.assertFalse(any(p=='ETH-BTC' for p,s,a,b in plan['directions']))
        self.assertGreater(plan['missing_independent_paths'],0)
        self.assertIn('BTC-USD',plan['books'])

    def test_excluded_or_disabled_products_are_never_requested_as_routes_or_marks(self):
        q,rules=market();rules['BTC-USD']['view_only']=True
        plan=select_books(list(q),rules,{'BTC','USD'},quotes={},now=NOW,excluded={'ETH'})
        self.assertEqual(plan['books'],[])
        self.assertEqual(plan['directions'],[])

    def test_endpoint_quota_leaves_discovery_capacity_and_deduplicates_shared_books(self):
        q,rules=broad_market(50)
        groups=[{'books':(p,),'earliest':NOW,'deadline':NOW+120+i} for i,p in enumerate(q)]
        plan=select_books(list(q),rules,{'USD'},quotes={},now=NOW,priority_groups=groups)
        self.assertEqual(plan['endpoint_requests'],6)
        self.assertEqual(plan['books'][:6],list(q)[:6])
        self.assertEqual(len(plan['books']),16)
        self.assertGreaterEqual(len(plan['directions']),10)
        self.assertEqual(plan['endpoint_groups_deferred'],44)
        duplicate=select_books(list(q),rules,{'USD'},quotes={},now=NOW,priority_groups=[groups[0]]*20)
        self.assertEqual(duplicate['endpoint_requests'],1)

    def test_prehorizon_cache_does_not_satisfy_due_request_and_expired_requests_drop(self):
        q,rules=market()
        group={'books':('ETH-USD',),'earliest':NOW,'deadline':NOW+120}
        earlier=dict(q,**{'ETH-USD':(D(2600),D('2600.01'),NOW-1)})
        plan=select_books(list(q),rules,set(),quotes=earlier,now=NOW,priority_groups=[group])
        self.assertEqual(plan['books'],['ETH-USD'])
        self.assertEqual(select_books(list(q),rules,set(),quotes=q,now=NOW,priority_groups=[group])['books'],[])
        expired=dict(group,earliest=NOW-200,deadline=NOW-80)
        self.assertEqual(select_books(list(q),rules,set(),quotes={},now=NOW,priority_groups=[expired])['books'],[])

    def test_public_get_rate_and_retry_after_are_preserved(self):
        clock=[0.0];budget=GetBudget(clock=lambda:clock[0]);times=[]
        def sleep(seconds):clock[0]+=seconds
        for i in range(16):
            budget.acquire(6,sleep=sleep);times.append(clock[0])
        self.assertAlmostEqual(times[-1],3)
        self.assertTrue(all(b-a>=.199999 for a,b in zip(times,times[1:])))
        budget.postpone('120')
        with self.assertRaises(QuoteDeferred):budget.acquire(6,sleep=sleep)
        self.assertGreaterEqual(budget.blocked_until,123)


class EndpointObservations(unittest.TestCase):
    def test_due_groups_are_pure_fixed_paths_deadlines_not_profit_or_quantities(self):
        q,rules=market();lab=PassiveLab();result=scan();lab.observe(result,q,now=NOW)
        before=deepcopy(lab.__dict__)
        groups=lab.quote_groups(now=NOW+300,listed=q)
        self.assertEqual(lab.__dict__,before)
        self.assertTrue(groups)
        self.assertTrue(all(set(g)=={'books','earliest','deadline','horizon','wait_passes','jobs'} for g in groups))
        self.assertTrue(all(g['horizon'] in (300,900,3600) and g['wait_passes']>=0 for g in groups))
        self.assertEqual(lab.quote_groups(now=NOW+299,listed=q),[])
        self.assertTrue(all(g['deadline']==NOW+420 for g in groups))
        self.assertTrue(all('ETH-USD' in g['books'] for g in groups))

    def test_quotes_just_before_horizon_remain_unknown_until_endpoint_observed(self):
        q,rules=market();lab=PassiveLab();lab.observe(scan(),q,now=NOW)
        early={p:(b[0],b[1],NOW+299) for p,b in q.items()}
        lab.observe({'ranked':[]},early,now=NOW+300)
        self.assertEqual(lab.counts['300_ABOVE_HOLD']+lab.counts['300_NOT_ABOVE_HOLD'],0)
        fresh={p:(b[0],b[1],NOW+301) for p,b in q.items()}
        lab.observe({'ranked':[]},fresh,now=NOW+301)
        self.assertGreater(lab.counts['300_ABOVE_HOLD']+lab.counts['300_NOT_ABOVE_HOLD'],0)

    def test_wide_and_skewed_endpoints_expire_as_missed_with_causes_not_losses(self):
        q,rules=market();result=scan()
        result=dict(result,ranked=[result['best']])
        for kind in ('WIDE','PRICE_SKEW'):
            lab=PassiveLab();lab.observe(result,q,now=NOW)
            future={p:(b[0],b[1],NOW+300) for p,b in q.items()}
            if kind=='WIDE':future['BTC-USD']=(D(50000),D(60000),NOW+300)
            else:future['ETH-USD']=(D(2600),D('2600.01'),NOW+317)
            lab.observe({'ranked':[]},future,now=NOW+320)
            lab.observe({'ranked':[]},{},now=NOW+421)
            self.assertGreater(lab.counts['300_MISSED'],0)
            cause='BOOK_WIDE' if kind=='WIDE' else 'PRICE_SKEW'
            self.assertGreater(lab.missed_causes['300_'+cause],0)
            self.assertEqual(lab.counts['300_NOT_ABOVE_HOLD'],0)

    def test_endpoint_never_switches_to_a_new_favorable_mark_path(self):
        q,rules=market();lab=PassiveLab();lab.observe(scan(),q,now=NOW)
        future={p:(b[0],b[1],NOW+300) for p,b in q.items() if p!='ETH-USD'}
        lab.observe({'ranked':[]},future,now=NOW+300)
        self.assertEqual(lab.counts['300_ABOVE_HOLD'],0)
        self.assertTrue(any(row['blocked'].get(300)=='BOOK_UNOBSERVED' for row in lab.pending.values()))

    def test_due_quotes_are_collected_inside_same_scanner_budget_and_complete_comparisons(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=gui.setup(folder);s.refresh(now=NOW)
            s.scan(now=NOW,collect=gui.collector(client))
            calls=[]
            def collect(pairs,**kwargs):
                calls.append(tuple(pairs))
                return gui.collector(client,at=NOW+300)(pairs,**kwargs)
            result=s.scan(now=NOW+300,collect=collect)
            self.assertEqual(len(calls),1)
            self.assertLessEqual(len(calls[0]),16)
            self.assertGreater(result['quote_scheduling']['endpoint_groups_scheduled'],0)
            self.assertGreater(s.lab.counts['300_ABOVE_HOLD']+s.lab.counts['300_NOT_ABOVE_HOLD'],0)

    def test_deadline_share_refreshes_old_observations_instead_of_only_next_discovery_page(self):
        completed=[]
        for prioritize in (False,True):
            with TemporaryDirectory() as folder:
                ledger,client,s=broad_scanner(folder)
                s.scan(now=NOW,collect=gui.collector(client))
                original=s.lab.quote_groups
                if not prioritize:
                    s.lab.quote_groups=lambda **kwargs:[]
                result=s.scan(now=NOW+300,collect=gui.collector(client,at=NOW+300))
                s.lab.quote_groups=original
                completed.append(s.lab.counts['300_ABOVE_HOLD']+s.lab.counts['300_NOT_ABOVE_HOLD'])
                self.assertLessEqual(result['quote_scheduling']['requested_books'],16)
        self.assertEqual(completed,[0,6])


class CoverageIntegration(unittest.TestCase):
    def test_844_direction_rotation_prices_every_direction_without_relaxing_freshness(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=broad_scanner(folder,844);before=gui.ledger_dump(ledger)
            now=NOW;requests=[];complete=False
            for index in range(100):
                batch=[]
                def collect(pairs,**kwargs):
                    batch.extend(pairs)
                    return gui.collector(client,at=now)(pairs,**kwargs)
                result=s.scan(now=now,collect=collect)
                requests.append(len(batch))
                self.assertLessEqual(len(batch),16)
                self.assertLessEqual(result['quote_scheduling']['endpoint_requests'],6)
                self.assertEqual(result['eligible_directions'],844)
                self.assertEqual(sum(result['book_conditions'].values()),844)
                self.assertTrue(all(0<=now-book[2]<=30 for book in s.books.values()))
                if result['coverage_history']['session_priced_directions']==844:
                    complete=True;break
                now+=8  # Includes a representative collection plus manual 5s pause.
            self.assertTrue(complete)
            self.assertFalse(result['coverage_complete'])
            self.assertLess(result['priced_directions'],844)
            self.assertEqual(before,gui.ledger_dump(ledger))
            self.assertEqual(set(client.calls),{'permissions','accounts','products','fees'})
            self.assertFalse(result['live_order_permission'])
            print('SYNTHETIC 844-direction rotation:',index+1,'passes;',now-NOW,
                'simulated seconds; max',max(requests),'GETs/pass;',result['priced_directions'],'fresh priced;',
                result['coverage_history']['session_priced_directions'],'session distinct')

    def test_stale_unobserved_and_recent_session_coverage_are_separate(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=broad_scanner(folder)
            first=s.scan(now=NOW,collect=gui.collector(client))
            self.assertEqual(first['priced_directions'],16)
            self.assertEqual(first['book_conditions'],{'FRESH':16,'UNOBSERVED':24})
            empty=lambda pairs,**kwargs:({}, {}, 0)
            stale=s.scan(now=NOW+40,collect=empty)
            self.assertEqual(stale['priced_directions'],0)
            self.assertEqual(stale['book_conditions'],{'STALE':16,'UNOBSERVED':24})
            self.assertEqual(stale['coverage_history']['last_5min_priced_directions'],16)
            later=s.scan(now=NOW+400,collect=empty)
            self.assertEqual(later['coverage_history']['session_priced_directions'],16)
            self.assertEqual(later['coverage_history']['last_5min_priced_directions'],0)
            self.assertEqual(s.books,{})

    def test_book_condition_classes_do_not_weaken_quote_acceptance(self):
        cases={
            'UNOBSERVED':None,'STALE':(D(100),D('100.01'),NOW-31),
            'FRESH':(D(100),D('100.01'),NOW),'FUTURE':(D(100),D('100.01'),NOW+1),
            'WIDE':(D(100),D(110),NOW),'INVALID':(D('NaN'),D(100),NOW)}
        for expected,book in cases.items():self.assertEqual(book_status(book,NOW),expected)
        self.assertEqual(book_status((),NOW),'INVALID')

    def test_stop_during_due_collection_preserves_all_new_state_and_observations(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=gui.setup(folder);s.refresh(now=NOW)
            s.scan(now=NOW,collect=gui.collector(client));s.refresh(now=NOW+300)
            before=(deepcopy(s.observed_books),deepcopy(s.priced_at),deepcopy(s.lab.__dict__),s.sequence,s.cursor)
            stop=threading.Event()
            def collect(pairs,**kwargs):
                stop.set();return gui.collector(client,at=NOW+300)(pairs,**kwargs)
            self.assertEqual(s.scan(now=NOW+300,collect=collect,cancel=stop)['state'],'CANCELLED')
            self.assertEqual(before,(s.observed_books,s.priced_at,s.lab.__dict__,s.sequence,s.cursor))


class CoverageGUI(unittest.TestCase):
    setUp=gui.SimpleGUI.setUp
    def test_partial_hold_and_export_explain_scope_missing_books_and_endpoint_causes(self):
        from coincat_simple_diagnostics import make_report
        app=self.app;client=BroadClient(40)
        app.scanner=Scanner(app.ledger,client,app.fees,app.market)
        app.scanner.refresh(now=NOW)
        result=app.scanner.scan(now=NOW,collect=gui.collector(client))
        app.last_result=result;app._render(result)
        self.assertIn('16/40',app.best_text.get())
        self.assertIn('UNKNOWN',app.best_text.get())
        self.assertIn('historical, not fresh coverage',app.coverage_text.get())
        self.root.geometry('1040x800');self.root.update()
        self.assertGreaterEqual(app.wallet_tree.winfo_height(),60)
        report=make_report(app,now=NOW)
        for text in ('COMPLETE (8/8)','UNOBSERVED','book_conditions','quote_scheduling',
                     'CURRENTLY_PRICED_DIRECTIONS_ONLY','missed_endpoint_causes'):
            self.assertIn(text,report)
        self.assertNotIn('eth_observation',report)
        self.assertNotIn(str(app.ledger.path),report)
        self.assertIn('never-observed/stale/wide',settings_advice(result))
        self.assertFalse(app.running)
