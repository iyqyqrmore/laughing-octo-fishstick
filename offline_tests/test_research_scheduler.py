"""Admission, fair deadlines and coherent ETH groups; synthetic/offline only."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json,math,threading,unittest

from coincat_research_admission import AdmissionCalendar,service_period
from coincat_passive_lab import PassiveLab,HORIZONS
from coincat_v80_discovery import select_books
from coincat_v701_transport import ScoutCollector,QuoteErrors,QuoteDeferred,QuoteSnapshot
from coincat_eth_farmer import eth_quote_plan,measure_eth
from coincat_full_balance import rank_full_balances
from coincat_scanner import Scanner
from offline_tests.test_v91_full_balance import scan,market,NOW
from offline_tests.test_quote_coverage import broad_market
from offline_tests import test_v91_scanner_gui as gui
from offline_tests.research_replay import run_replay


def isolated_jobs(count=1):
    """Seed isolated due jobs for adversarial scheduler tests, not UI data."""
    lab=PassiveLab();rules={}
    for horizon in HORIZONS:
        for n in range(count):
            prefix=f'H{horizon}N{n}'
            source,target=prefix+'A',prefix+'C'
            source_path=(source+'-'+prefix+'B',prefix+'B-USD')
            target_path=(target+'-'+prefix+'D',prefix+'D-USD')
            books=tuple(sorted(set(source_path+target_path+('ETH-USD',))))
            for p in books:
                rules[p]=dict(product_id=p,product_type='SPOT',status='online',base_increment='.00000001',
                    base_min_size='.00000001',quote_min_size='.00000001',quote_increment='.00000001')
            key=f'{horizon}_{n}'
            lab.pending[key]={'at':NOW-horizon-(20 if horizon==300 else 10 if horizon==900 else 0),
                'source':source,'target':target,'spent':D(1),'received':D(1),
                'source_path':source_path,'target_path':target_path,'books':books,'excluded':(),
                'done':set(HORIZONS)-{horizon},'blocked':{},'scheduled':set(),'deferred':set(),
                'attempted_at':{},'transport_failure':{},'retry_after':{}}
    return lab,rules


class Admission(unittest.TestCase):
    def test_refused_observation_is_distinct_from_repeated_review_attempts_and_misses(self):
        q,rules=market();lab=PassiveLab(capacity=1);result=scan()
        lab.observe(result,q,now=NOW);lab.observe(result,q,now=NOW+1)
        d=lab.diagnostics()
        self.assertEqual(len(lab.pending),1)
        self.assertEqual(d['admission']['considered_distinct'],2)
        self.assertEqual(d['admission']['admitted_distinct'],1)
        self.assertEqual(d['admission']['not_admitted_distinct'],1)
        self.assertEqual(d['admission']['repeated_not_admitted_review_attempts'],1)
        self.assertEqual(d['admission']['not_admitted_review_attempts'],2)
        self.assertTrue(all(h['not_admitted']==1 and h['missed']==0 for h in d['horizons'].values()))

    def test_three_future_windows_must_fit_before_any_job_is_admitted(self):
        q,rules=broad_market(100)
        result=rank_full_balances(balances={'USD':D(1000)},catalog=list(q),rules=rules,
            quotes=q,fee_rate=D('.009'),now=NOW,balances_at=NOW)
        lab=PassiveLab();lab.observe(result,q,now=NOW)
        self.assertGreater(lab.admission['admitted_distinct'],0)
        self.assertGreater(lab.admission['not_admitted_distinct'],0)
        self.assertLess(len(lab.pending),lab.capacity)
        self.assertTrue(any(k.startswith('NO_SERVICE_CAPACITY_') for k in lab.admission_reasons))
        self.assertEqual(lab.admission['considered_distinct'],
                         lab.admission['admitted_distinct']+lab.admission['not_admitted_distinct'])
        self.assertTrue(all(not row['done'] for row in lab.pending.values()))

    def test_calendar_rolls_back_all_reservations_when_a_later_horizon_cannot_fit(self):
        cal=AdmissionCalendar(now=NOW,period=12)
        for slot in range(math.floor((NOW+900)/12),math.ceil((NOW+1020)/12)+1):
            if slot%3==1:cal.slots[slot]=frozenset('ABCDEF')
        before=deepcopy(cal.slots)
        accepted,reason=cal.reserve({'at':NOW,'done':set(),'books':('G',)})
        self.assertFalse(accepted)
        self.assertEqual(reason,'NO_SERVICE_CAPACITY_900')
        self.assertEqual(before,cal.slots)

    def test_admission_rotates_direction_order_instead_of_following_profit_ranking(self):
        q,rules=broad_market(100);lab=PassiveLab()
        def result(at):
            books={p:(b[0],b[1],at) for p,b in q.items()}
            ranked=rank_full_balances(balances={'USD':D(1000)},catalog=list(q),rules=rules,
                quotes=books,fee_rate=D('.009'),now=at,balances_at=at)
            return ranked,books
        ranked,books=result(NOW);lab.observe(ranked,books,now=NOW)
        first={row['target'] for row in lab.pending.values()}
        ranked,books=result(NOW+300);lab.observe(ranked,books,now=NOW+300)
        later={row['target'] for row in lab.pending.values() if row['at']==NOW+300}
        self.assertTrue(later-first)

    def test_actual_manual_cadence_constrains_admission_without_changing_a_setting(self):
        q,rules=broad_market(50)
        result=rank_full_balances(balances={'USD':D(1000)},catalog=list(q),rules=rules,
            quotes=q,fee_rate=D('.009'),now=NOW,balances_at=NOW)
        fast=PassiveLab();slow=PassiveLab()
        fast.observe(result,q,now=NOW,scan_interval_s=5)
        slow.observe(result,q,now=NOW,scan_interval_s=60)
        self.assertLessEqual(slow.admission['admitted_distinct'],fast.admission['admitted_distinct'])
        self.assertEqual(slow.period,67)
        self.assertEqual(service_period(5),12)
        for cadence in (4,61,float('nan')):
            with self.assertRaises(ValueError):service_period(cadence)

    def test_backoff_and_unusable_dependencies_are_not_admitted_not_future_losses(self):
        q,rules=market()
        for changes in ({'quote_errors':{'HTTP_429_RETRY_AFTER':1}},{}):
            lab=PassiveLab();result=dict(scan(),**changes)
            books=q if changes else {p:(b[0],b[1],NOW-31) for p,b in q.items()}
            lab.observe(result,books,now=NOW)
            self.assertEqual(lab.admission['admitted_distinct'],0)
            self.assertEqual(lab.admission['not_admitted_distinct'],2)
            self.assertFalse(lab.pending)
            self.assertTrue(all(h['missed']==0 for h in lab.diagnostics()['horizons'].values()))

    def test_distinct_decision_tracking_is_bounded_and_overflow_is_not_claimed_distinct(self):
        candidate=scan()['best'];rows=[]
        for n in range(4100):rows.append(dict(candidate,pair=f'F{n:04d}-USD'))
        lab=PassiveLab(capacity=0);lab.observe({'ranked':rows},{},now=NOW)
        self.assertEqual(len(lab.decisions),4096)
        self.assertEqual(lab.admission['not_admitted_distinct'],4096)
        self.assertEqual(lab.admission['decision_tracking_overflow_attempts'],4)


class DeadlineFairness(unittest.TestCase):
    def test_hourly_jobs_get_service_by_fourth_pass_under_continuous_short_window_pressure(self):
        lab,rules=isolated_jobs(10);quotes={};served=[]
        for turn in range(4):
            now=NOW+turn*12
            groups=lab.quote_groups(now=now,listed=rules)
            before=deepcopy(lab.__dict__)
            plan=select_books(list(rules),rules,set(),quotes=quotes,now=now,priority_groups=groups)
            self.assertEqual(lab.__dict__,before)
            self.assertLessEqual(plan['endpoint_requests'],6)
            incoming={p:(D(100),D('100.01'),now) for p in plan['books']};quotes.update(incoming)
            served.append({h for key,h in plan['_research_scheduled']})
            lab.record_service(plan,incoming,{},now=now)
            lab.observe({'ranked':[]},quotes,now=now)
        self.assertEqual(served[0],{300})  # EDF is retained before starvation debt.
        self.assertTrue(any(3600 in turn for turn in served))
        self.assertTrue(all(any(h in turn for turn in served) for h in HORIZONS))
        self.assertGreater(lab.counts['3600_NOT_ABOVE_HOLD'],0)
        self.assertLessEqual(lab.horizon_stats[3600]['max_completion_lag_s'],36)

    def test_deferral_attempts_and_distinct_deferred_jobs_are_separate_per_horizon(self):
        lab,rules=isolated_jobs(1)
        for turn in range(2):
            now=NOW+turn*12
            plan=select_books(list(rules),rules,set(),quotes={},now=now,
                priority_groups=lab.quote_groups(now=now,listed=rules))
            incoming={p:(D(100),D('100.01'),now) for p in plan['books']}
            lab.record_service(plan,incoming,{},now=now)
        stats=lab.diagnostics()['horizons']['3600']
        self.assertEqual(stats['request_deferral_attempts'],2)
        self.assertEqual(stats['distinct_deferred_observations'],1)
        self.assertEqual(stats['scheduled_attempts'],0)

    def test_terminal_failure_uses_actual_transport_attribution_and_does_not_repeat_attempt_count(self):
        q,rules=market();lab=PassiveLab();result=scan();result=dict(result,ranked=[result['best']])
        lab.observe(result,q,now=NOW)
        plan=select_books(list(q),rules,set(),quotes={},now=NOW+300,
            priority_groups=lab.quote_groups(now=NOW+300,listed=q))
        errors=QuoteErrors(HTTP_429_RETRY_AFTER=1);errors.by_product={'BTC-USD':'HTTP_429_RETRY_AFTER'}
        incoming={'ETH-USD':(D(2600),D('2600.01'),NOW+300)}
        lab.record_service(plan,incoming,errors,now=NOW+300)
        lab.observe({'ranked':[]},incoming,now=NOW+300)
        lab.observe({'ranked':[]},incoming,now=NOW+301)
        lab.observe({'ranked':[]},{},now=NOW+421)
        stats=lab.diagnostics()['horizons']['300']
        self.assertEqual(stats['failed_attempts'],1)
        self.assertEqual(stats['terminal_missed_causes'],{'REQUEST_HTTP_429_RETRY_AFTER':1})
        self.assertEqual(lab.counts['300_NOT_ABOVE_HOLD'],0)

    def test_collector_attributes_error_classes_without_exporting_messages(self):
        import requests
        def fetch(pair,**kwargs):
            if pair=='BTC-USD':raise ValueError('SENSITIVE_TEST_MESSAGE')
            if pair=='SOL-USD':
                response=requests.Response();response.status_code=503
                raise requests.HTTPError('SENSITIVE_TEST_MESSAGE',response=response)
            return QuoteSnapshot(pair,D(100),D('100.01'),NOW,NOW,1)
        got,errors,elapsed=ScoutCollector().collect(['BTC-USD','ETH-USD','SOL-USD'],fetch=fetch)
        self.assertEqual(set(got),{'ETH-USD'})
        self.assertEqual(dict(errors),{'ValueError':1,'HTTP_503':1})
        self.assertEqual(errors.by_product,{'BTC-USD':'ValueError','SOL-USD':'HTTP_503'})
        self.assertNotIn('SENSITIVE_TEST_MESSAGE',str(errors))

    def test_reference_failure_is_distinct_from_successful_usd_comparison(self):
        q,rules=market();result=scan()
        sale=next(row for row in result['ranked'] if row['pair']=='BTC-USD')
        lab=PassiveLab();lab.observe(dict(result,ranked=[sale]),q,now=NOW)
        plan=select_books(list(q),rules,set(),quotes={},now=NOW+300,
            priority_groups=lab.quote_groups(now=NOW+300,listed=q))
        incoming={'BTC-USD':(D(50000),D('50000.01'),NOW+300)}
        errors=QuoteErrors(HTTP_503=1);errors.by_product={'ETH-USD':'HTTP_503'}
        lab.record_service(plan,incoming,errors,now=NOW+300)
        lab.observe({'ranked':[]},incoming,now=NOW+300)
        stats=lab.diagnostics()['horizons']['300']
        self.assertEqual(stats['completed'],1)
        self.assertEqual(stats['missed'],0)
        self.assertEqual(stats['eth_unpriced'],1)
        self.assertEqual(stats['eth_unpriced_causes'],{'REQUEST_HTTP_503':1})

    def test_congested_three_hour_replay_improves_each_horizon_and_capacity_attempts(self):
        baseline=json.loads((Path(__file__).with_name('research_replay_baseline.json')).read_text())
        actual=run_replay()
        self.assertLessEqual(actual['max_unique_gets'],16)
        self.assertLessEqual(actual['max_pending'],512)
        self.assertGreater(actual['admission']['not_admitted_distinct'],0)
        self.assertLess(actual['capacity_deferral_attempts'],baseline['capacity_deferral_attempts'])
        for h in HORIZONS:
            old=baseline['outcomes'][str(h)];new=actual['outcomes'][h]
            old_rate=old['completed']/(old['completed']+old['missed'])
            new_rate=new['completed']/(new['completed']+new['missed'])
            self.assertGreater(new_rate,old_rate)
            self.assertGreater(new['completed'],old['completed'])
        print('SYNTHETIC 3-hour research replay:',json.dumps(actual,sort_keys=True))


class ETHSynchronization(unittest.TestCase):
    def test_full_small_account_group_refreshes_reference_and_dependencies_together(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=gui.setup(folder);s.refresh(now=NOW)
            s.observed_books={p:(b[0],b[1],NOW-20) for p,b in client.q.items()}
            s.books=dict(s.observed_books);requested=[]
            def collect(pairs,**kwargs):
                requested.extend(pairs);return gui.collector(client)(pairs,**kwargs)
            result=s.scan(now=NOW,collect=collect)
            self.assertEqual(set(requested),set(client.q))
            self.assertEqual(result['eth_quote_scheduling']['selected_group_kind'],'account')
            self.assertTrue(result['eth_quote_scheduling']['selected_group_synchronized'])
            value=measure_eth(result={'ranked':[]},**result['eth_observation'])
            self.assertEqual(value['quote_span_s'],0)
            self.assertEqual(value['synchronization_state'],'SYNCHRONIZED')
            self.assertIsNone(value['hold']['estimated_recoverable_eth'])  # Dust is not magically ETH.
            self.assertEqual(value['scope'],'ACCOUNT_AVAILABLE_ONLY_NOT_RECONCILED_WORKING_FUNDS')

    def test_eth_only_available_account_can_be_measured_without_claiming_settlement_or_earnings(self):
        q,rules=market();balances={'ETH':D(2)}
        group=eth_quote_plan(balances=balances,catalog=list(q),rules=rules)
        self.assertEqual(group['groups'][0]['books'],('ETH-USD',))
        value=measure_eth(result={'ranked':[]},balances=balances,catalog=list(q),rules=rules,
            quotes=q,now=NOW,balances_at=NOW,fee_rate=D('.009'))
        self.assertEqual(value['hold']['estimated_recoverable_eth'],D(2))
        self.assertIsNone(value['settled_eth']);self.assertIsNone(value['earned_eth'])
        self.assertIsNone(value['protected_eth'])

    def test_large_account_gets_atomic_subset_groups_and_never_a_fabricated_total(self):
        q,rules=broad_market(28);q['ETH-USD']=(D(100),D('100.01'),NOW)
        rules['ETH-USD']=dict(next(iter(rules.values())),product_id='ETH-USD')
        balances={p.split('-')[0]:D(1) for p in q if p!='ETH-USD'}
        group=eth_quote_plan(balances=balances,catalog=list(q),rules=rules)
        plan=select_books(list(q),rules,set(),quotes={},now=NOW,valuation_groups=group['groups'])
        self.assertEqual(group['account_required_books'],29)
        self.assertEqual(plan['_eth_group']['kind'],'asset')
        self.assertLessEqual(len(plan['books']),16)
        self.assertIn('ETH-USD',plan['books'])
        books={p:(b[0],b[1],NOW if p in plan['books'] else NOW-20) for p,b in q.items()}
        value=measure_eth(result={'ranked':[]},balances=balances,catalog=list(q),rules=rules,
            quotes=books,now=NOW,balances_at=NOW,fee_rate=D('.009'))
        self.assertEqual(value['state'],'UNKNOWN')
        self.assertEqual(value['reason'],'ETH_RETURN_PRICE_SKEW')
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])

    def test_unknown_assets_remain_unconverted_and_excluded_holdings_are_not_requested(self):
        q,rules=market();balances={'ETH':D(2),**{f'MYST{i}':D(1) for i in range(27)}}
        group=eth_quote_plan(balances=balances,catalog=list(q),rules=rules,excluded={'BTC'})
        self.assertEqual(group['missing_asset_count'],27)
        self.assertFalse(group['all_paths_supported'])
        self.assertIsNone(group['account_required_books'])
        self.assertTrue(all(g['kind']!='account' for g in group['groups']))
        self.assertTrue(all(g['books']==('ETH-USD',) for g in group['groups']))
        value=measure_eth(result={'ranked':[]},balances=balances,catalog=list(q),rules=rules,
            quotes=q,now=NOW,balances_at=NOW,fee_rate=D('.009'))
        self.assertEqual(len(value['hold']['unconverted_native']),27)
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])
        self.assertIsNone(value['cashflow_adjusted_gain_eth'])

    def test_research_share_and_eth_groups_combined_cannot_exceed_global_limit(self):
        q,rules=broad_market(50);q['ETH-USD']=(D(100),D('100.01'),NOW)
        rules['ETH-USD']=dict(next(iter(rules.values())),product_id='ETH-USD')
        priority=[{'books':(p,),'earliest':NOW,'deadline':NOW+120} for p in list(q)[:10]]
        valuation=[{'kind':'account','books':tuple(list(q)[10:]+['ETH-USD'])},
                   {'kind':'asset','asset':'C0010','books':('C0010-USD','ETH-USD')}]
        plan=select_books(list(q),rules,{'USD'},quotes={},now=NOW,
            priority_groups=priority,valuation_groups=valuation)
        self.assertEqual(plan['endpoint_requests'],6)
        self.assertLessEqual(len(plan['books']),16)
        self.assertEqual(plan['_eth_group']['kind'],'asset')
        self.assertIn('ETH-USD',plan['books'])


class Integration(unittest.TestCase):
    def test_stop_preserves_forecasts_counters_fairness_and_eth_cursor(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=gui.setup(folder);s.refresh(now=NOW)
            s.scan(now=NOW,collect=gui.collector(client));s.refresh(now=NOW+300)
            before=(deepcopy(s.lab.__dict__),s.eth_cursor,gui.ledger_dump(ledger))
            cancel=threading.Event()
            def collect(pairs,**kwargs):
                cancel.set();return gui.collector(client,at=NOW+300)(pairs,**kwargs)
            self.assertEqual(s.scan(now=NOW+300,collect=collect,cancel=cancel)['state'],'CANCELLED')
            self.assertEqual(before,(s.lab.__dict__,s.eth_cursor,gui.ledger_dump(ledger)))

    def test_mixer_reserve_and_passive_advisor_are_unchanged_from_previous_commit(self):
        import ast,hashlib
        root=Path(__file__).resolve().parents[1]
        hashes={'coincat_mixer.py':'d6ac98c3f73253832fcf6996a53cb6f72b55620394205c6a52fe9a9bfb55285e',
                'coincat_settings_advisor.py':'2a6d5c6e0c8ad211bc60065e5f9563cf3834bef39433b278c9e85781f7cdfad7'}
        for name,digest in hashes.items():
            self.assertEqual(hashlib.sha256((root/'app'/name).read_bytes()).hexdigest(),digest,name)
        source=(root/'app/coincat_eth_farmer.py').read_text()
        tree=ast.parse(source)
        # Trusted baseline source bytes, independent of Python's AST schema.
        for name,digest in {'ReservePolicy':'9db702080e72721c09ac88402620b98e0fa27181e6084d882ca7c86d40b4b23e',
                            'reserve_preview':'aa8bdd26787cc792b2a853197f147d92e1ea96d160b7f723014ea015f2ea8a71'}.items():
            node=next(n for n in tree.body if getattr(n,'name',None)==name)
            self.assertEqual(hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest(),digest)
        from coincat_eth_farmer import reserve_preview,ReservePolicy
        self.assertTrue(ReservePolicy.__dataclass_params__.frozen)
        proposal=reserve_preview(fixed_reference=D(2000))
        self.assertEqual(proposal['initial_target_eth'],D('.005'))
        self.assertFalse(proposal['assets_earmarked'])
        self.assertIsNone(proposal['actual_earned_eth'])
        from coincat_settings_advisor import settings_advice
        self.assertIn('no setting changed',settings_advice({}))

    def test_scheduler_diagnostics_are_per_horizon_and_redact_observation_ids_and_quantities(self):
        from types import SimpleNamespace as NS
        from coincat_simple_diagnostics import make_report
        with TemporaryDirectory() as folder:
            ledger,client,s=gui.setup(folder);s.refresh(now=NOW)
            result=s.scan(now=NOW,collect=gui.collector(client))
            row=next(iter(s.lab.pending.values()))
            row['received']=D('9876543.2109876')
            s.lab.pending['PRIVATE_OBSERVATION_ID']=s.lab.pending.pop(next(iter(s.lab.pending)))
            app=NS(scanner=s,last_result=result,ledger=ledger,connected=True,running=False,
                   busy=False,last_error=None,eth_measurement=measure_eth(result=result,**result['eth_observation']))
            report=make_report(app,now=NOW)
            for value in ('PRIVATE_OBSERVATION_ID','9876543.2109876',str(ledger.path)):
                self.assertNotIn(value,report)
            for value in ('COMPLETE (8/8)','research_scheduler','not_admitted_distinct',
                          'request_deferral_attempts','distinct_deferred_observations',
                          'attempt_failure_causes','terminal_missed_causes','eth_quote_scheduling',
                          'ACCOUNT_AVAILABLE_ONLY_NOT_RECONCILED_WORKING_FUNDS'):
                self.assertIn(value,report)
            self.assertEqual(set(s.lab.diagnostics()['horizons']),{'300','900','3600'})
