"""Measured existing work, never synthetic execution or connected readiness."""
from copy import deepcopy
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import patch
import unittest

from coincat_v90_telemetry import DirectionCoverage, ResearchCycles, age_detail
from coincat_v80_immediate import rank, diagnostic_report
from offline_tests import test_v80_discovery as discovery
from offline_tests.v80_fixtures import reference, NOW


ELIGIBLE=[('AAA-BTC','BUY','BTC','AAA'),('AAA-BTC','SELL','AAA','BTC'),
          ('AAA-ETH','BUY','ETH','AAA'),('AAA-USD','SELL','AAA','USD')]


def measured(key, at, *, complete=True):
    return {'direction':key,'evaluated_at':at,'size_trials':3,
            'priced_sizes':3 if complete else 0,
            'state':'ECONOMIC_NEGATIVE' if complete else 'NOT_PRICED',
            'blockers':['W_NONPOSITIVE'] if complete else ['PRICE_SKEW']}


class Coverage(unittest.TestCase):
    def test_repeated_activity_is_one_distinct_direction_and_negative_is_priced(self):
        tracker=DirectionCoverage()
        for now in (100,110,120):
            tracker.select(ELIGIBLE,ELIGIBLE[:1],now=now,cycle_id=str(now))
            tracker.record([measured(('AAA-BTC','BUY'),now)],ELIGIBLE[:1],now=now,reason='RESEARCHED')
        s=tracker.summary(now=120)
        self.assertEqual(s['eligible_directions'],4)
        self.assertEqual(s['distinct_complete_in_window'],1)
        self.assertEqual(s['complete_events_in_window'],3)
        self.assertEqual(s['never_evaluated'],3)
        self.assertEqual(s['never_complete'],3)
        self.assertEqual(s['by_market_quote']['BTC']['eligible'],2)
        self.assertEqual(s['by_market_quote']['ETH']['never_complete'],1)
        self.assertEqual(tracker.ages(now=130)[('AAA-BTC','BUY')]['last_complete_age_s'],10)

    def test_unpriced_and_never_evaluated_are_separate_from_overdue(self):
        tracker=DirectionCoverage()
        tracker.select(ELIGIBLE,ELIGIBLE[:2],now=100,cycle_id='one')
        tracker.record([measured(('AAA-BTC','BUY'),100),
                        measured(('AAA-BTC','SELL'),100,complete=False)],
                       ELIGIBLE[:2],now=100,reason='RESEARCHED')
        s=tracker.summary(now=161)
        self.assertEqual((s['never_complete'],s['overdue_complete'],s['recent_complete']),(3,1,0))
        self.assertEqual(s['eligible_directions'],s['never_complete']+s['overdue_complete']+s['recent_complete'])
        self.assertEqual(s['never_evaluated'],2)
        self.assertEqual(s['evaluation_events_in_window'],0)
        self.assertEqual(s['oldest_complete_age_s'],61)

    def test_selection_without_receipt_does_not_claim_an_evaluation(self):
        tracker=DirectionCoverage()
        tracker.select(ELIGIBLE,ELIGIBLE[:1],now=100,cycle_id='one')
        tracker.record([],ELIGIBLE[:1],now=101,reason='NO_FRESH_TARGET_BOOK')
        row=tracker.ages(now=101)[('AAA-BTC','BUY')]
        self.assertIsNone(row['last_evaluated_at'])
        self.assertIsNone(row['last_complete_at'])
        self.assertEqual(row['latest_reason'],'NO_PRICING_EVALUATION:NO_FRESH_TARGET_BOOK')

    def test_removal_and_reentry_start_a_new_eligibility_interval(self):
        tracker=DirectionCoverage()
        tracker.select(ELIGIBLE,ELIGIBLE[:1],now=100,cycle_id='one')
        tracker.record([measured(('AAA-BTC','BUY'),100)],ELIGIBLE[:1],now=100,reason='OK')
        tracker.select([],[],now=101,cycle_id='two')
        tracker.select(ELIGIBLE,[],now=102,cycle_id='three')
        s=tracker.summary(now=102)
        self.assertEqual(s['never_complete'],4)
        self.assertEqual(s['distinct_complete_in_window'],0)
        self.assertEqual(tracker.ages(now=102)[('AAA-BTC','BUY')]['eligible_since'],102)

    def test_bounded_window_reports_dropped_observations(self):
        tracker=DirectionCoverage(max_events=2)
        tracker.select(ELIGIBLE,ELIGIBLE[:1],now=100,cycle_id='one')
        for now in (100,101,102,103):
            tracker.record([measured(('AAA-BTC','BUY'),now)],ELIGIBLE[:1],now=now,reason='OK')
        s=tracker.summary(now=104)
        self.assertTrue(s['window_truncated'])
        self.assertEqual(s['dropped_window_events_total'],2)
        self.assertEqual(s['evaluation_events_in_window'],2)
        self.assertFalse(tracker.summary(now=200)['window_truncated'])

    def test_cycle_ids_survive_equal_timestamps_and_distinguish_app_runs(self):
        clock=ResearchCycles()
        a,b=clock.begin(100),clock.begin(100)
        c=ResearchCycles().begin(100)
        self.assertEqual(len({a['id'],b['id'],c['id']}),3)
        self.assertEqual(a['started_at'],100)

    def test_freshness_preserves_stale_missing_and_clock_conflict(self):
        self.assertEqual(age_detail(100,80,15),{'age_s':20,'limit_s':15,'state':'STALE'})
        self.assertEqual(age_detail(100,None,15)['state'],'UNOBSERVED')
        self.assertEqual(age_detail(100,101,15)['state'],'CLOCK_CONFLICT')
        self.assertEqual(age_detail(100,99,15)['state'],'FRESH')


class ActualPricingMeasurements(unittest.TestCase):
    def test_all_sizes_are_measured_before_display_truncation(self):
        idea,quotes,rules=reference()
        rows=[]
        shown,s=rank([deepcopy(idea) for _ in range(15)],quotes,rules,now=NOW,limit=1,evaluations=rows)
        self.assertEqual(len(shown),1)
        self.assertEqual(s['size_trials'],15)
        self.assertEqual(sum(s['size_state_counts'].values()),15)
        self.assertEqual(s['distinct_routes'],1)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['size_trials'],15)
        self.assertEqual(rows[0]['priced_sizes'],15)

    def test_route_outcome_is_priced_if_any_size_is_priced_regardless_of_order(self):
        valid,q,rules=reference()
        # A current but uneconomic route is a complete evaluation.
        q['ETH-USD']=(D(2500),D('2500.01'),NOW)
        invalid=deepcopy(valid);invalid['source_units']=D(0)
        for ideas in ([invalid,valid],[valid,invalid]):
            rows=[];shown,s=rank(ideas,q,rules,now=NOW,evaluations=rows)
            self.assertEqual((s['size_trials'],s['priced_sizes'],s['unpriced_sizes']),(2,1,1))
            self.assertEqual((s['distinct_routes'],s['negative_routes'],s['unpriced_routes']),(1,1,0))
            self.assertEqual(rows[0]['priced_sizes'],1)
            self.assertEqual(s['size_state_counts'],{'NOT_PRICED':1,'ECONOMIC_NEGATIVE':1})


class ActualHandoffMeasurements(unittest.TestCase):
    def fixture(self, folder):
        return discovery.StaticDiscovery.fixture(self,folder)

    def test_cycle_link_session_reconciliation_stop_retention_and_rearm(self):
        with TemporaryDirectory() as folder:
            app,clock,q,rules,fetch=self.fixture(folder)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                first=app._fast_cycle();n=len(first['plan']['ideas'])
                self.assertGreater(n,0)
                app._apply_fast_experimental(first)
                app._fast_last_result=first
                self.assertIn('SAME_CYCLE_REEVALUATED_AT_CONSUMER',diagnostic_report(app))
                model=app.experimental_shadow
                self.assertEqual(model.immediate_funnel['cycle']['id'],first['research_cycle']['id'])
                clock[0]+=31
                app._apply_fast_experimental(first)
                totals=model.reconciliation()
                self.assertEqual(totals['observations'],2)
                self.assertEqual(totals['submitted_sizes'],2*n)
                self.assertEqual(totals['preconsumer_rejected_sizes'],n)
                self.assertEqual(totals['reviewed_sizes'],n)
                self.assertTrue(totals['reconciliation_ok'])
                model.disarm(now=clock[0])
                retained=deepcopy(model.reconciliation())
                second=app._fast_cycle()
                self.assertNotEqual(first['research_cycle']['id'],second['research_cycle']['id'])
                self.assertEqual(model.reconciliation(),retained)
                app._fast_last_result=second
                text=diagnostic_report(app)
                self.assertIn('DIFFERENT_CYCLES',text)
                self.assertIn('DISARMED; retained session results',text)
                self.assertEqual(model.snapshot(now=clock[0])['immediate_session_reconciliation'],retained)
                clock[0]+=1
                model.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
                    usd_coverage=True,enrolled_quantities={'BTC':'.002'},
                    fresh_usd_rates={'BTC':'50000','USD':'1'},now=clock[0])
                self.assertEqual(model.reconciliation()['preconsumer_rejections'],{})
                self.assertNotIn('observations',model.immediate_session_totals)
                app.broker.submit.assert_not_called()

    def test_actual_discovery_records_complete_direction_and_separate_denominators(self):
        with TemporaryDirectory() as folder:
            app,clock,q,rules,fetch=self.fixture(folder)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                payload=app._fast_cycle()
                coverage=payload['direction_coverage'];f=payload['immediate_funnel']
                self.assertGreater(coverage['distinct_complete_in_window'],0)
                self.assertEqual(coverage['cycle_id'],payload['research_cycle']['id'])
                self.assertIn('completed_at',f['cycle'])
                self.assertEqual(f['distinct_routes'],sum(f[k] for k in
                    ('positive_unverified_routes','negative_routes','zero_routes','unpriced_routes')))
                self.assertEqual(f['selected_directions'],f['selected_without_costed_receipt']+f['selected_with_costed_receipt'])
                self.assertLessEqual(f['unpriced_routes'],f['distinct_routes'])
                self.assertNotIn('_direction_evaluations',payload)
                app.broker.submit.assert_not_called()

    def test_snapshot_before_any_consumer_is_explicitly_unlinked(self):
        with TemporaryDirectory() as folder:
            app,clock,q,rules,fetch=self.fixture(folder)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                app._fast_last_result=app._fast_cycle()
                self.assertIn('Consumer cycle relation: UNLINKED',diagnostic_report(app))
                self.assertEqual(app.experimental_shadow.fifo_posted,0)

    def test_selected_missing_books_never_claim_complete_evaluation(self):
        with TemporaryDirectory() as folder:
            app,clock,q,rules,fetch=self.fixture(folder)
            clock[0]+=31
            # Empty fetched/cached books make the real producer exit early.
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),\
                 patch('coincat_app.SCOUT.collect',return_value=({}, {'SYNTHETIC_UNAVAILABLE':1},0)),\
                 patch.object(app,'_shadow_valuation_books',return_value={}):
                payload=app._fast_cycle()
                self.assertEqual(payload['direction_coverage']['distinct_complete_in_window'],0)
                self.assertEqual(payload['immediate_funnel']['size_trials'],0)
                self.assertEqual(payload['immediate_funnel']['unpriced_routes'],0)
                self.assertGreater(payload['immediate_funnel']['selected_without_costed_receipt'],0)
                app.broker.submit.assert_not_called()


class TimedFreshness(unittest.TestCase):
    def test_readiness_snapshots_keep_stale_and_recovered_heartbeats_separate(self):
        from coincat_go_live_readiness import gather_readiness,readiness_report
        app=NS(_last_poll_heartbeat=80,_last_tick_heartbeat=80)
        stale=gather_readiness(app,wall=NOW,mono=100)
        self.assertEqual(stale['freshness']['ui_poll']['state'],'STALE')
        self.assertEqual(stale['freshness']['ui_poll']['age_s'],20)
        app._last_poll_heartbeat=101;app._last_tick_heartbeat=101
        fresh=gather_readiness(app,wall=NOW+2,mono=102)
        self.assertEqual(fresh['freshness']['ui_poll']['state'],'FRESH')
        self.assertNotEqual(stale['freshness']['snapshot_utc'],fresh['freshness']['snapshot_utc'])
        self.assertEqual(stale['freshness']['ui_poll']['state'],'STALE')
        report=readiness_report(app,wall=NOW+2,mono=102)
        self.assertIn('Freshness observation:',report)
        self.assertIn('OVERALL: NOT APPROVED',report)

    def test_default_session_totals_are_explicitly_unobserved(self):
        from coincat_v80_shadow import StrictImmediateShadow
        s=StrictImmediateShadow(experimental=True)
        r=s.reconciliation()
        self.assertEqual(r['state'],'NOT_OBSERVED')
        self.assertEqual(r['observations'],0)
        self.assertEqual(r['submitted_sizes'],0)
