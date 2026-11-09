"""Adverse outcomes, original HOLD, finite orders and strict exported facts."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import json
import unittest
from coincat_beta_store import BetaBlocked
from coincat_intelligent_market import quality,can_decide
from coincat_intelligent_policy import IntelligentConfig,evaluate
from coincat_intelligent_public import validate
from coincat_maker_shadow import active
from coincat_portfolio_performance import append_point,rolling
from coincat_watchlist import WATCH_ASSETS
from offline_tests import test_intelligent_execution as execution
from offline_tests.intelligent_fixtures import frame

class Evidence(unittest.TestCase):
    setUpClass=classmethod(execution.IntelligentExecution.setUpClass.__func__)
    setUp=execution.IntelligentExecution.setUp
    f=execution.IntelligentExecution.f
    order=execution.IntelligentExecution.order
    fill=execution.IntelligentExecution.fill

    def test_ineligible_pair_does_not_block_other_twelve_directions_or_native_hour_coverage(self):
        f=self.f();f['rules']['ADA-ETH']['view_only']=True
        wallet=f['account']['available'];rows,best=evaluate(f,wallet,wallet,wallet,[],IntelligentConfig())
        self.assertEqual(len(rows),14);self.assertTrue(quality(f)[0]);self.assertTrue(can_decide(f))
        self.assertTrue(all(r['state']=='HOLD' for r in rows if r['pair']=='ADA-ETH'))
        self.assertIsNotNone(best);self.assertNotEqual(best['pair'],'ADA-ETH')
        del f['books']['ADA-ETH'];self.assertEqual(quality(f),(False,6))
        self.e.review(f);p=self.e.public();self.assertEqual(p['market_coverage'],6);self.assertEqual(p['valuation_coverage'],5)
        self.assertEqual(p['direction_checks'],14);self.assertIsNotNone(active(self.e.state()))
        self.c.tick(10);self.e.heartbeat();self.assertEqual(self.e.progress()['valid_seconds'],0)

    def test_native_fee_and_unfavorable_inventory_mark_reduce_value_vs_unchanged_hold(self):
        o=self.order();self.assertEqual(o['projection']['target'],'BTC');self.fill(o)
        before=self.e.state();self.c.tick(31);rows=deepcopy(self.hist);rows[-1]['marks']['BTC']*=D('.8')
        f=frame(self.c,rows,prediction=self.initial['forecast']);f['forecast'].update(decision_at=self.c.wall(),forecast_end_at=self.c.wall()+86400)
        self.e.review(f);s=self.e.state();p=s['last_performance']
        self.assertLess(p['advantage_usd'],0);self.assertGreater(s['max_drawdown'],0)
        self.assertEqual(s['original'],before['original']);self.assertEqual(s['fees_native'],before['fees_native'])
        self.assertTrue(all(r['state']=='HOLD' for r in s['rows']));self.assertIsNone(active(s))
        self.assertIn('FORECAST_CURRENT_PRICE_SHOCK',{r['reason'] for r in s['rows']})

    def test_cancel_reprice_keeps_original_campaign_remaining_budget_and_attempt_limit(self):
        o=self.order();original=deepcopy(self.e.state()['campaigns'][o['campaign']]);inc=D(o['rules']['base_increment'])
        original_frame=self.f
        def only_pair():
            f=original_frame()
            for pair,rule in f['rules'].items():
                if pair!=o['pair']:rule['view_only']=True
            return f
        self.f=only_pair
        self.fill(o,(o['size']/4//inc)*inc,trade='initial-partial')
        for attempt in range(3):
            current=deepcopy(active(self.e.state()));self.c.tick(120);f=self.f();tick=D(current['rules']['price_increment'])
            shift=(-4*tick if current['side']=='SELL' else 4*tick)*(attempt+1)
            b=f['books'][current['pair']]
            for key in ('bid','ask'):b[key]+=shift
            for key in ('bids','asks'):b[key]=tuple((p+shift,q) for p,q in b[key])
            self.e.review(f);self.assertEqual(active(self.e.state())['state'],'CANCEL_PENDING')
            self.assertEqual(self.e.state()['metrics']['orders'],attempt+1)
            self.c.tick(3);self.e.heartbeat();self.assertIsNone(active(self.e.state()))
            self.c.tick(30);f['at']=self.c.wall()
            replacement=self.f();replacement['books'][current['pair']]=deepcopy(b);replacement['books'][current['pair']]['at']=self.c.wall()
            self.e.review(replacement);child=active(self.e.state());self.assertIsNotNone(child)
            root=self.e.state()['campaigns'][o['campaign']]
            self.assertEqual(child['campaign'],o['campaign']);self.assertEqual(root['expires_at'],original['expires_at'])
            self.assertEqual(root['budget'],original['budget']);self.assertLessEqual(child['size'],root['initial_size']-root['filled'])
            self.assertLessEqual(child['reserved'],root['budget']-root['spent'])
            self.c.tick(10);f=self.f();f['books'][child['pair']]=deepcopy(b);f['books'][child['pair']]['at']=self.c.wall()
            f['market_trades']=dict(pair=child['pair'],at=self.c.wall(),prints=[]);self.e.review(f)
        self.assertEqual(self.e.state()['campaigns'][o['campaign']]['attempts'],4)
        self.c.tick(601);self.e.heartbeat();self.c.tick(3);self.e.heartbeat()
        self.assertIsNone(active(self.e.state()));self.c.tick(30);self.e.review(self.f())
        root=self.e.state()['campaigns'][o['campaign']];self.assertTrue(root['closed']);self.assertEqual(root['attempts'],4)

    def test_public_trade_through_can_only_create_capped_conditional_partial_and_gap_cannot_fill(self):
        o=self.order()
        for i in range(3):
            self.c.tick(10);p=o['price']+D('.000001') if o['side']=='SELL' else o['price']-D('.000001')
            self.prints.append(dict(id='through'+str(i),price=p,size=D(1000),at=self.c.wall()));self.e.review(self.f())
        s=self.e.state();self.assertEqual(s['metrics']['modeled_fills'],1);self.assertEqual(s['metrics']['replay_fills'],0)
        partial=active(s);self.assertEqual(partial['state'],'PARTIAL');self.assertLessEqual(partial['filled'],o['size']*D('.25'))
        old=partial['filled'];self.c.tick(10);self.prints=[dict(id='gap',price=p,size=D(100000),at=self.c.wall())];self.e.review(self.f())
        self.assertEqual(active(self.e.state())['filled'],old);self.assertEqual(self.e.state()['metrics']['gaps'],1)

    def test_no_fill_provider_preserves_wallet_and_costs_even_with_trade_through_evidence(self):
        self.e.pending_config=replace(IntelligentConfig(),provider='NO_FILL_OBSERVATION_V1');o=self.order();wallet=self.e.state()['wallet']
        for i in range(4):
            self.c.tick(10);self.prints.append(dict(id='nofill'+str(i),price=o['price']*D('1.001'),size=D(100000),at=self.c.wall()));self.e.review(self.f())
        self.assertEqual(self.e.state()['wallet'],wallet);self.assertEqual(self.e.state()['metrics']['fill_events'],0)
        self.assertTrue(all(q==0 for q in self.e.state()['fees_native'].values()))

    def test_missing_reference_cancels_at_review_and_retains_inventory_with_no_replacement(self):
        self.order();before=self.e.state()['wallet'];self.c.tick(31);f=self.f();del f['reference_books']['SOL-USD'];self.e.review(f)
        self.assertEqual(active(self.e.state())['state'],'CANCEL_PENDING');self.assertIsNone(self.e.view()['performance'])
        self.c.tick(3);self.e.heartbeat();self.assertIsNone(active(self.e.state()));self.assertEqual(self.e.state()['wallet'],before)
        self.assertEqual(self.e.state()['metrics']['orders'],1);self.assertEqual(self.e.state()['metrics']['fill_events'],0)

    def test_partial_native_coverage_does_not_hide_marks_with_fresh_synchronized_usd_references(self):
        self.order();self.c.tick(31);f=self.f();del f['books']['ADA-ETH'];self.e.review(f)
        self.assertIsNotNone(self.e.view()['performance']);self.assertFalse(self.e.lease['valid'])

    def test_forward_24_hour_forecast_records_wrong_direction_and_unknown_gap_without_cherry_picking(self):
        f=self.f();self.e.review(f);self.assertEqual(self.e.state()['prediction_counts']['registered'],1)
        self.e.pause();self.c.tick(86400);rows=deepcopy(self.hist);rows[-1]['marks']['BTC']*=D('.9')
        observed=frame(self.c,rows,prediction=self.initial['forecast']);self.e.start();self.e.review(observed)
        counts=self.e.state()['prediction_counts'];self.assertEqual(counts['known'],1)
        self.assertGreater(counts['direction_checks'],0);self.assertEqual(counts['direction_matches'],0)
        self.assertLess(self.e.state()['predictions'][0]['actual']['BTC'],0)
        # A separately registered forecast whose exact horizon was missed is
        # permanently UNKNOWN, even if a later quote would look favorable.
        f=self.f();f['forecast']['feature_at']=self.c.wall();self.c.tick(31);f=self.f();f['forecast']['feature_at']=self.c.wall();self.e.review(f)
        self.assertEqual(self.e.state()['prediction_counts']['registered'],2)
        self.c.tick(86521);self.e.review(self.f());self.assertEqual(self.e.state()['prediction_counts']['unknown'],1)

    def test_public_allowlist_has_only_fixed_labels_counts_and_rejects_amounts_at_every_level(self):
        self.order();p=self.e.public();validate(p);text=json.dumps(p)
        for secret in (self.e.state()['trial_id'],'OPP-','wallet','seed_marks','projected_advantage_usd','forecast_provenance','price'):
            self.assertNotIn(secret,text)
        for location,key in (((), 'wallet'),(('rejection_breakdown',),'portfolio_usd'),(('rejection_breakdown','categories'),'BTC')):
            bad=deepcopy(p);node=bad
            for part in location:node=node[part]
            node[key]='PRIVATE'
            with self.assertRaises(ValueError):validate(bad)
        for key in ('live_order_authority','horizon_s','selected_policy','version','history_references','market_coverage'):
            bad=deepcopy(p);bad[key]=True
            with self.subTest(key=key),self.assertRaises(ValueError):validate(bad)

    def test_stale_actual_references_block_decisions_and_marks_even_if_frame_time_is_recent(self):
        f=self.f();f['forecast']=dict(state='HOLD',reason='FORECAST_HISTORY_INSUFFICIENT');self.e.review(f)
        self.c.tick(31);f=self.f();self.c.tick(20);f['at']=self.c.wall()
        for b in f['reference_books'].values():b['at']-=20
        self.e.review(f);self.assertEqual(self.e.state()['metrics']['orders'],0)
        self.assertIsNone(self.e.view()['performance']);self.assertEqual(self.e.public()['data_state'],'PARTIAL')
        self.assertEqual(self.e.public()['valuation_coverage'],0)

class RollingPerformance(unittest.TestCase):
    def test_negative_rolling_results_and_observation_gaps_stay_distinct(self):
        s=dict(performance_history=[])
        for at in range(0,86401,300):
            loss=D(at)/86400;append_point(s,dict(at=at,portfolio_usd=500-loss,hold_usd=D(500),advantage_usd=-loss))
        current=s['performance_history'][-1];values=rolling(s['performance_history'],current)
        for key in ('1h','6h','24h'):
            self.assertEqual(values[key]['state'],'MARKED_WITH_OBSERVED_COVERAGE');self.assertLess(values[key]['advantage_change_usd'],0)
        sparse=[r for r in s['performance_history'] if not 80000<r['at']<82000]
        self.assertEqual(rolling(sparse,current)['6h']['state'],'OBSERVATION_GAP')
