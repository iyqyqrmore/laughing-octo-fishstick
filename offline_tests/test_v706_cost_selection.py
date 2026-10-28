"""Synthetic causal learning, current-cost selection and actual chain tests.

No network, user data, financial DB or predictive performance assertion.
"""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
import unittest

from coincat_live_forward_store import ForwardStore
from coincat_v507_shadow_arm import ShadowArmedResearch,experimental_shadow_report
from coincat_v706_selection import (ForwardCostLearner,assess,features,
    GRACE_S)
from offline_tests.selection_fixtures import calibrated
from offline_tests.test_v703_chain_contract import make_plan,NOW
from offline_tests import test_v703_chain_contract as chain_fixtures


def stream(pair='BTC-USD',pct='1',age=0):
    return {'rows':[{'pair':pair,'change_30s_pct':pct,'age_ms':age}]}


def books(now,price='100'):
    value=D(price)
    return {'BTC-USD':(value,value*D('1.0001'),now)}


def train(learner,*,start=NOW-2400,growth='1.02',count=8,pct='1'):
    """Record real learner endpoints in an explicitly artificial price series."""
    result=None
    for n in range(count+1):
        stamp=start+n*300;quote=books(stamp,str(D(100)*D(growth)**n))
        result=learner.observe(catalog=list(quote),quotes=quote,
            snapshot=stream(pct=pct),now=stamp,observed_pairs=quote)
    return result,quote,stamp


class CausalPublicLearning(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=ForwardStore(Path(self.temp.name)/'synthetic-public.sqlite')
        self.learner=self.store.selection

    def observe(self,stamp,quote=None,pct='1',pairs=('BTC-USD',)):
        quote=books(stamp) if quote is None else quote
        return self.learner.observe(catalog=list(quote),quotes=quote,
            snapshot=stream(pct=pct),now=stamp,observed_pairs=pairs)

    def forecast(self,stamp,pct='1'):
        return self.learner.forecasts(pairs=['BTC-USD'],snapshot=stream(pct=pct),now=stamp)

    def test_exact_nonoverlapping_endpoints_and_restart_persistence(self):
        self.assertEqual(self.observe(NOW)['recorded'],1)
        self.assertEqual(self.observe(NOW+299)['matured'],0)
        self.assertEqual(self.observe(NOW+299)['recorded'],0)
        self.assertEqual(self.observe(NOW+300,books(NOW+300,'102'))['matured'],1)
        fresh=ForwardCostLearner(self.store.path)
        with fresh._db() as db:
            rows=db.execute('SELECT * FROM v706_forward_cost ORDER BY opened_at').fetchall()
        self.assertEqual([r['state'] for r in rows],['OBSERVED','PENDING'])
        self.assertEqual(D(rows[0]['growth_buy']),D('.02'))
        self.assertGreaterEqual(rows[1]['opened_at'],rows[0]['closed_at'])
        self.assertEqual(fresh.summary()['observations'],{'OBSERVED':1,'PENDING':1})

    def test_eight_windows_required_with_no_training_lookahead(self):
        _,quote,stamp=train(self.learner,count=7)
        waiting=self.forecast(stamp)['BTC-USD','BUY']
        self.assertEqual(waiting['state'],'WAIT_FORWARD_OBSERVATIONS')
        self.assertEqual(waiting['observed_windows'],7)
        end=stamp+300
        self.observe(end,books(end,str(D(100)*D('1.02')**8)))
        ev=self.forecast(end)['BTC-USD','BUY']
        self.assertEqual(ev['state'],'READY_EXPERIMENTAL')
        self.assertEqual(D(ev['mean_relative_growth']),D('.02'))
        self.assertEqual(D(ev['p25_relative_growth']),D('.02'))
        # Rewind lookup cannot read the eighth later outcome.
        rewound=self.forecast(stamp)['BTC-USD','BUY']
        self.assertEqual(rewound['observed_windows'],7)
        self.assertEqual(rewound['state'],'WAIT_FORWARD_OBSERVATIONS')

    def test_features_actual_pair_freshness_and_exact_inverse(self):
        f=features(stream(pct='-20'),NOW)['BTC-USD']
        self.assertEqual(f['BUY'],'DOWN_STRONG');self.assertEqual(f['SELL'],'UP_STRONG')
        self.assertEqual(features(stream(age=30001),NOW),{})
        self.assertEqual(features(stream(age=-1),NOW),{})
        self.assertEqual(features(stream(pct='NaN'),NOW),{})
        self.assertEqual(features(stream(pct='-100'),NOW),{})
        train(self.learner)
        self.assertEqual(self.learner.forecasts(pairs=['ETH-BTC'],snapshot=stream(),now=NOW),{})
        mismatched=self.forecast(NOW,pct='-2')['BTC-USD','BUY']
        self.assertEqual(mismatched['observed_windows'],0)

    def test_missed_labels_not_backfilled_by_later_gains(self):
        self.observe(NOW)
        self.observe(NOW+300+GRACE_S+1,books(NOW+421,'1000'))
        ev=self.forecast(NOW+421)['BTC-USD','BUY']
        self.assertEqual(ev['observed_windows'],0)
        self.assertEqual(ev['missing_windows'],1)
        with self.learner._db() as db:
            first=db.execute('SELECT state,growth_buy FROM v706_forward_cost ORDER BY opened_at LIMIT 1').fetchone()
        self.assertEqual(tuple(first),('MISSED',None))

    def test_stale_wide_missing_and_skewed_books_do_not_label(self):
        self.observe(NOW)
        for quote in (books(NOW+260),{'BTC-USD':('100','110',NOW+300)},{}):
            self.assertEqual(self.observe(NOW+300,quote)['matured'],0)
        quote={'BTC-USD':('100','100.01',NOW+300),
            'ETH-USD':('10','10.001',NOW+280),'ETH-BTC':('.1','.10001',NOW+300)}
        self.learner.observe(catalog=list(quote),quotes=quote,snapshot=stream('ETH-BTC'),
            now=NOW+300,observed_pairs=['ETH-BTC'])
        with self.learner._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM v706_forward_cost WHERE pair='ETH-BTC'").fetchone()[0],0)

    def test_sell_growth_is_inverse_relative_growth(self):
        train(self.learner)
        ev=self.forecast(NOW)['BTC-USD','SELL']
        expected=1/D('1.02')-1
        self.assertAlmostEqual(D(ev['mean_relative_growth']),expected,places=25)
        self.assertLess(D(ev['p25_relative_growth']),0)

    def test_relative_coin_growth_matters_even_when_both_usd_prices_fall(self):
        for n in range(9):
            stamp=NOW-2400+n*300
            source=D(100)*D('.95')**n;target=D(10)*D('.98')**n
            quote={'BTC-USD':(source,source*D('1.0001'),stamp),
                'ETH-USD':(target,target*D('1.0001'),stamp),
                'ETH-BTC':(target/source,target/source*D('1.0001'),stamp)}
            self.learner.observe(catalog=list(quote),quotes=quote,snapshot=stream('ETH-BTC'),
                now=stamp,observed_pairs=['ETH-BTC'])
        forecasts=self.learner.forecasts(pairs=['ETH-BTC'],snapshot=stream('ETH-BTC'),now=NOW)
        ev=forecasts['ETH-BTC','BUY']
        self.assertAlmostEqual(D(ev['mean_relative_growth']),D('.98')/D('.95')-1,places=25)
        idea=make_plan('BTC','ETH',quantity='1',books=quote)
        idea['forward_edge_evidence']=ev
        self.assertGreater(assess(idea,now=NOW)['score_usd'],0)
        reverse=make_plan('ETH','BTC',quantity='1',books=quote)
        reverse['forward_edge_evidence']=forecasts['ETH-BTC','SELL']
        self.assertIsNone(assess(reverse,now=NOW)['score_usd'])

    def test_pending_overdue_misses_count_in_coverage_before_maintenance(self):
        train(self.learner)
        ev=self.forecast(NOW+421)['BTC-USD','BUY']
        self.assertEqual(ev['observed_windows'],8)
        self.assertEqual(ev['missing_windows'],1)

    def test_sql_busy_defers_learning_without_waiting_for_trade_or_write(self):
        with sqlite3.connect(self.store.path) as lock:
            lock.execute('BEGIN IMMEDIATE')
            result=self.observe(NOW)
        self.assertEqual(result['state'],'DEFERRED_MODEL_BUSY')
        self.assertEqual(self.learner.summary()['observations'],{})

    def test_invalid_public_entry_does_not_interrupt_worker_or_invent_growth(self):
        self.observe(NOW)
        with self.learner._db() as db:
            db.execute("UPDATE v706_forward_cost SET entry_ratio='NaN'")
        result=self.observe(NOW+300)
        self.assertEqual(result['missed'],1)
        self.assertEqual(result['matured'],0)

    def test_public_schema_contains_no_positions_and_refuses_financial_database(self):
        with self.learner._db() as db:
            columns={r[1] for r in db.execute('PRAGMA table_info(v706_forward_cost)')}
        self.assertEqual(columns,{'pair','opened_at','due_at','closed_at','buy_context','sell_context','entry_ratio','growth_buy','state'})
        path=Path(self.temp.name)/'synthetic-financial.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE fills(id TEXT)');db.execute("INSERT INTO fills VALUES('KEEP')")
        before=path.read_bytes()
        with self.assertRaises(ValueError):ForwardCostLearner(path)
        self.assertEqual(before,path.read_bytes())

    def test_pending_prefix_does_not_starve_other_approved_books(self):
        pairs=[f'A{i:02}-USD' for i in range(40)]
        snap={'rows':[{'pair':p,'change_30s_pct':1,'age_ms':0} for p in pairs]}
        for delta,expected in ((0,32),(1,8)):
            quote={p:('1','1.0001',NOW+delta) for p in pairs}
            stats=self.learner.observe(catalog=pairs,quotes=quote,snapshot=snap,
                now=NOW+delta,observed_pairs=pairs)
            self.assertEqual(stats['recorded'],expected)
        self.assertEqual(self.learner.summary()['observations'],{'PENDING':40})

    def test_unapproved_pair_is_never_an_observation(self):
        self.learner.observe(catalog=[],quotes=books(NOW),snapshot=stream(),
            now=NOW,observed_pairs=['BTC-USD'])
        self.assertEqual(self.learner.summary()['observations'],{})


class CurrentCostSelection(unittest.TestCase):
    def test_raw_momentum_is_discovery_only_and_immediate_requires_actual_gain(self):
        idea=make_plan();idea.pop('forward_edge_evidence')
        self.assertIsNone(assess(idea,now=NOW)['score_usd'])
        idea.update(snowball_state='IMMEDIATE_ESTIMATE',snowball_immediate_usd='10')
        self.assertIsNone(assess(idea,now=NOW)['score_usd'])
        idea['shadow_fifo_steps'][0]['output_usd_mark']='11'
        policy=assess(idea,now=NOW)
        self.assertEqual(policy['basis'],'IMMEDIATE_AFTER_COST')
        self.assertGreater(policy['score_usd'],0)
        self.assertIsNone(policy['evidence_key'])

    def test_current_costs_once_and_no_dollar_floor_or_nominal_cap_bonus(self):
        for cap in ('1','10'):
            with self.subTest(cap=cap):
                idea=make_plan(cap=cap)
                inp=idea['shadow_fifo_steps'][0]['approx_usd_notional']
                out=idea['shadow_fifo_steps'][0]['output_usd_mark']
                expected=out*D('1.024')-inp
                self.assertEqual(assess(idea,now=NOW)['score_usd'],expected)
                self.assertEqual(assess(dict(idea,research_size_cap_usd='1000000'),now=NOW)['score_usd'],expected)
                self.assertGreater(expected,0)

    def test_both_mean_and_lower_quartile_must_pay_current_fees(self):
        idea=make_plan()
        for mean,low in (('.03','0'),('0','.03'),('-.01','-.02')):
            candidate=deepcopy(idea)
            candidate['forward_edge_evidence'].update(mean_relative_growth=mean,p25_relative_growth=low)
            self.assertEqual(assess(candidate,now=NOW)['reason'],'CURRENT_COSTS_EXCEED_FORWARD_EDGE')
        expensive=deepcopy(idea);step=expensive['shadow_fifo_steps'][0]
        step.update(fee_rate_used=D('.03'),approx_usd_notional=step['output_usd_mark']*D('1.03'))
        self.assertIsNone(assess(expensive,now=NOW)['score_usd'])

    def test_identical_fee_formatting_cannot_reopen_used_forecast(self):
        idea=make_plan();first=assess(idea,now=NOW)['evidence_key']
        idea['shadow_fifo_steps'][0]['fee_rate_used']=D('.009000')
        self.assertEqual(assess(idea,now=NOW)['evidence_key'],first)
        idea['shadow_fifo_steps'][0]['fee_rate_used']=D('.008')
        self.assertNotEqual(assess(idea,now=NOW)['evidence_key'],first)
        for bad in ('NaN','-0.1','.05'):
            idea['shadow_fifo_steps'][0]['fee_rate_used']=bad
            self.assertIsNone(assess(idea,now=NOW)['score_usd'])

    def test_future_stale_mismatched_insufficient_and_missing_evidence_rejected(self):
        changes=({'asof':NOW+1},{'asof':NOW-31},{'feature_at':NOW-31},
            {'last_label_at':NOW+1},{'last_label_at':NOW-721},
            {'first_opened_at':float('nan')},{'pair':'ETH-USD'},{'side':'SELL'},
            {'observed_windows':7},{'missing_windows':3},{'nonoverlap_verified':False},
            {'mean_relative_growth':'NaN'},{'p25_relative_growth':'-1'},
            {'context':'UNKNOWN'},{'horizon_s':60})
        for change in changes:
            with self.subTest(change=change):
                idea=make_plan();idea['forward_edge_evidence'].update(change)
                self.assertIsNone(assess(idea,now=NOW)['score_usd'])

    def test_feature_and_label_do_not_receive_an_extra_payload_age_allowance(self):
        idea=make_plan()
        idea['forward_edge_evidence']['feature_at']=NOW-29
        self.assertIsNotNone(assess(idea,now=NOW)['score_usd'])
        self.assertIsNone(assess(idea,now=NOW+2)['score_usd'])
        idea['forward_edge_evidence'].update(feature_at=NOW,last_label_at=NOW-719)
        self.assertIsNone(assess(idea,now=NOW+2)['score_usd'])

    def session(self):
        obj=ShadowArmedResearch(experimental=True)
        obj.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities={'USD':'1000'},fresh_usd_rates={'USD':'1'},now=NOW-1)
        self.addCleanup(lambda:[w.close() for w in obj.fifo_portfolios.values()])
        return obj

    def observe(self,obj,stamp,*,label=NOW,cap='10',budget=None):
        quote=books(stamp);idea=calibrated(make_plan(now=stamp,books=quote,cap=cap),stamp,label=label)
        obj.observe(now=stamp,quotes=quote,usd_rates={'USD':'1','BTC':'100'},route_ideas=[idea],
            strict_quotes=True,approved_catalog=['BTC-USD'],risk_budgets=budget)

    def test_same_forecast_not_reused_by_size_change_or_fresh_quote(self):
        obj=self.session()
        self.observe(obj,NOW)
        self.observe(obj,NOW+1,cap='5')
        self.observe(obj,NOW+10,cap='2')
        self.assertEqual(obj.fifo_posted,1)
        self.assertGreater(obj.selection_rejections.get('FORECAST_EVIDENCE_ALREADY_USED',0),0)
        self.observe(obj,NOW+300,label=NOW+300)
        self.assertEqual(obj.fifo_posted,2)
        self.assertEqual(obj.experimental_forward_posted,2)

    def test_failed_budget_does_not_consume_forward_evidence(self):
        obj=self.session()
        self.observe(obj,NOW,budget={'per_order_usd':'1','incremental_exposure_usd':'100',
            'daily_buy_usd':'1000','max_attempts':'100'})
        self.assertEqual(obj.fifo_posted,0);self.assertEqual(obj.used_forward_evidence,{})
        self.observe(obj,NOW+1)
        self.assertEqual(obj.fifo_posted,1)

    def test_failed_ram_receipt_does_not_consume_evidence_or_count(self):
        obj=self.session()
        with patch.object(obj,'_post_fifo',return_value=False):self.observe(obj,NOW)
        self.assertEqual(obj.fifo_posted,0);self.assertEqual(obj.used_forward_evidence,{})
        self.observe(obj,NOW+1)
        self.assertEqual(obj.fifo_posted,1)


class ActualCausalChain(unittest.TestCase):
    def test_cold_then_passive_calibration_same_fast_planner_fifo_and_pnl(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,rows=chain_fixtures.SyntheticWholeChain.fixture(self,folder)
            app.forward.selection=ForwardCostLearner(app.forward.path)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                cold=app._fast_cycle()
                self.assertEqual(cold['reason'],'OBSERVING_NO_COST_EDGE')
                self.assertEqual(app._apply_fast_experimental(cold),0)
                self.assertEqual(app.forward.selection.summary()['observations'],{'PENDING':1})
                # Training starts AFTER the cold decision. No future label at it.
                _,quote,end=train(app.forward.selection,start=NOW,count=8,pct='2.4')
                clock[0]=end
                fetch.side_effect=lambda pair,**kw: __import__('coincat_v701_transport').QuoteSnapshot(
                    pair,*quote[pair][:2],clock[0],clock[0],1)
                ready=app._fast_cycle()
                self.assertEqual(ready['reason'],'COST_EDGE_CANDIDATES')
                self.assertEqual(app._apply_fast_experimental(ready),1)
                self.assertEqual(app.experimental_shadow.entries[-1]['experimental_decision_basis'],'FORWARD_COST_SCENARIO')
                self.assertTrue(app.experimental_shadow.fifo_portfolios['TAKER_ASK'].quantity_parity())
                self.assertEqual(app.experimental_shadow.snapshot(now=clock[0])['real_order_submissions'],0)
                # A new public quote without a new outcome cannot spend again.
                clock[0]+=1
                repeated=app._fast_cycle()
                self.assertEqual(app._apply_fast_experimental(repeated),0)
            app.broker.submit.assert_not_called()
            report=experimental_shadow_report(app)
            self.assertIn('not confidence bounds',report)
            self.assertIn('Forward scenario: at least 8 nonoverlapping',report)
            self.assertNotIn('BTC-USD',report)

    def test_learning_runs_disarmed_and_has_no_fee_spending(self):
        with TemporaryDirectory() as folder:
            app,clock,text,fetch,rows=chain_fixtures.SyntheticWholeChain.fixture(self,folder)
            app.experimental_shadow.disarm()
            app.forward.selection=ForwardCostLearner(app.forward.path)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                result=app._fast_cycle()
            self.assertEqual(result['passive_selection']['recorded'],1)
            self.assertEqual(app.experimental_shadow.fifo_posted,0)
            app.broker.submit.assert_not_called()


class SyntheticWalkForwardComparison(unittest.TestCase):
    def test_replay_reports_churn_reduction_continuation_and_reversal_loss_honestly(self):
        from tools.replay_cost_selection import run
        result=run()
        self.assertEqual(result['real_order_submissions'],0)
        scenarios={s['scenario']:s for s in result['scenarios']}
        for scenario in scenarios.values():
            for outcome in scenario['policies'].values():self.assertTrue(outcome['quantity_parity'])
        for name in ('flat','one_jump_then_flat','reversing_rebounds'):
            new=scenarios[name]['policies']['forward_cost']
            self.assertEqual(new['conversions'],0)
            self.assertEqual(D(new['wallet_vs_hold_usd']),0)
        churn=scenarios['reversing_rebounds']['policies']
        self.assertGreater(churn['repeat_momentum']['conversions'],10)
        self.assertLess(D(churn['repeat_momentum']['wallet_vs_hold_usd']),0)
        trend=scenarios['artificial_continuation']['policies']['forward_cost']
        self.assertGreater(trend['conversions'],0)  # Not a blanket trading halt.
        reversal=scenarios['continuation_then_reversal']['policies']['forward_cost']
        self.assertGreater(reversal['conversions'],0)
        self.assertLess(D(reversal['wallet_vs_hold_usd']),0)  # Learned history can lose.


if __name__=='__main__':unittest.main()
