from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal as D
import unittest
import base64,zlib
from coincat_multi_trader import MultiTrader,encode_observation,decode_observation
from coincat_multi_policy import MultiConfig
from coincat_maker_shadow import active
from coincat_beta_store import BetaBlocked
from coincat_trial_clock import NS,TARGET_NS
from coincat_beta_store import pack
from coincat_intelligent_trader import IntelligentTrader
from coincat_assumed_math import rounded
from offline_tests.multi_fixtures import Clock,predictions,observed

class MultiExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.forecasts=predictions(Clock())
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.c=Clock();self.path=Path(self.tmp.name)/'multi.sqlite3'
        self.e=MultiTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns);self.e.start()
    def f(self):
        f=observed(self.c,self.forecasts)
        for row in f['horizon_forecasts'].values():
            if row['state']=='READY':row.update(decision_at=self.c.wall(),forecast_end_at=self.c.wall()+row['horizon_s'])
        return f
    def test_own_trial_identity_horizon_counts_and_private_projection_survive_restart(self):
        self.e.review(self.f());s=self.e.state();p=self.e.public();self.assertIsNotNone(active(s))
        self.assertEqual(s['strategy'],'MULTI_HORIZON_ONE_LEG_V1');self.assertEqual(p['direction_checks'],14)
        self.assertEqual(sum(r['checks'] for r in p['horizons'].values()),84);self.assertEqual(sum(r['selected_orders'] for r in p['horizons'].values()),1)
        self.e.shutdown();self.c.tick(7200);restored=MultiTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertFalse(restored.load_error)
        for key in ('trial_id','original','wallet','fees_native','config'):self.assertEqual(s[key],restored.state()[key])
        self.assertEqual(restored.progress()['valid_seconds'],0);self.assertEqual(restored.state()['metrics']['fill_events'],0)
    def test_fill_uses_one_native_commission_and_never_adds_a_reverse_leg(self):
        self.e.review(self.f());o=active(self.e.state());self.c.tick(10);f=self.f();f['market_trades']=dict(pair=o['pair'],at=self.c.wall(),prints=[]);self.e.review(f)
        receipt=dict(trade_id='once',product_id=o['pair'],side=o['side'],size=o['size'],price=o['price'],size_in_quote=False,
            commission=o['size']*o['price']*D('.005'),fee_currency=o['pair'].split('-')[1],liquidity_indicator='M')
        event=dict(source='EXPLICIT_SIMULATED_REPLAY',reference=o['reference'],kind='FILL',receipt=receipt,at=self.c.wall())
        self.e.replay(event,'event');s=self.e.state();self.e.replay(event,'event')
        self.assertEqual(self.e.state(),s);self.assertEqual(s['metrics']['fill_events'],1);self.assertIsNone(active(s))
        self.assertLess(s['last_performance']['advantage_usd'],0);self.assertEqual(sum(s['fees_native'].values()),receipt['commission'])
    def test_no_data_trial_can_complete_168_hours_without_a_trade_and_freezes(self):
        f=self.f();f['horizon_forecasts']={};self.e.review(f);self.e.store.clock['valid_ns']=TARGET_NS-10*NS;self.e.store.flush_clock()
        self.c.tick(10);self.e.heartbeat(persist=True);self.assertEqual(self.e.state()['mode'],'COMPLETE')
        p=self.e.write_report();raw=p.read_bytes();self.assertEqual(self.e.public()['orders'],0)
        self.e.shutdown();self.c.tick(1000);restored=MultiTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertFalse(restored.load_error);self.assertEqual(p.read_bytes(),raw)
        with self.assertRaises(BetaBlocked):restored.start()
    def test_long_trial_display_cache_retains_full_span_recent_rolling_history_and_financial_totals(self):
        self.e.review(self.f());before=self.e.state()
        def accumulate(s):
            for i in range(2100):
                at=self.c.wall()+i*300;perf=dict(at=at,portfolio_usd=D(500)-D(i)/10000,hold_usd=D(500),advantage_usd=-D(i)/10000)
                self.e.policy.mark(s,{},perf)
            self.e.policy.compact(s)
        self.e._change('SYNTHETIC_DISPLAY_HISTORY_STRESS',{},accumulate);s=self.e.state()
        self.assertLessEqual(len(s['performance_history']),1200);self.assertLess(len(pack(s).encode()),1048576)
        self.assertEqual(s['performance_history'][0]['at'],self.c.wall());self.assertEqual(s['performance_history'][-1]['at'],self.c.wall()+2099*300)
        recent=[p['at'] for p in s['performance_history'] if p['at']>=s['performance_history'][-1]['at']-24*3600]
        self.assertTrue(all(b-a==300 for a,b in zip(recent,recent[1:])))
        for key in ('original','wallet','fees_native','config'):self.assertEqual(s[key],before[key])
    def accept_order(self):
        self.e.review(self.f());o=active(self.e.state());self.c.tick(10);f=self.f();f['market_trades']=dict(pair=o['pair'],at=self.c.wall(),prints=[]);self.e.review(f)
        return active(self.e.state())
    def receipt(self,o,quantity,*,currency=True):
        r=dict(trade_id='native-part',product_id=o['pair'],side=o['side'],size=quantity,price=o['price'],size_in_quote=False,commission=quantity*o['price']*D('.005'))
        if currency:r['fee_currency']=o['pair'].split('-')[1]
        return dict(source='EXPLICIT_SIMULATED_REPLAY',reference=o['reference'],kind='FILL',receipt=r,at=self.c.wall())
    def test_partial_cancel_race_preserves_filled_inventory_and_only_charges_filled_quantity(self):
        o=self.accept_order();q=rounded(o['size']/2,D(o['rules']['base_increment']));self.e.pause();event=self.receipt(o,q);self.e.replay(event,'partial')
        self.assertEqual(active(self.e.state())['state'],'CANCEL_PENDING');self.c.tick(3);self.e.heartbeat(persist=True)
        s=self.e.state();self.assertIsNone(active(s));self.assertEqual(s['metrics']['fill_events'],1)
        self.assertEqual(s['fees_native'][o['pair'].split('-')[1]],event['receipt']['commission'])
    def test_unknown_fee_currency_locks_wallet_and_no_retry_is_authorized_after_restart(self):
        o=self.accept_order();before=self.e.state()['wallet'];self.e.replay(self.receipt(o,o['size'],currency=False),'unknown')
        self.assertEqual(self.e.state()['wallet'],before);self.assertEqual(self.e.public()['unresolved_orders'],1);self.assertFalse(self.e.running)
        self.e.shutdown();self.c.tick(3600);restored=MultiTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertFalse(restored.load_error);self.assertFalse(restored.running);self.assertEqual(restored.state()['wallet'],before)
        with self.assertRaises(BetaBlocked):restored.start()
    def test_quote_touch_and_elapsed_time_never_fill_and_child_expiry_cancels_without_fee(self):
        o=self.accept_order();before=self.e.state()['wallet']
        for i in range(5):
            self.c.tick(10);f=self.f();f['market_trades']=dict(pair=o['pair'],at=self.c.wall(),prints=[dict(id='touch'+str(i),price=o['price'],size=D(100000),at=self.c.wall())]);self.e.review(f)
        self.assertEqual(self.e.state()['metrics']['fill_events'],0);self.c.tick(601);self.e.heartbeat();self.c.tick(3);self.e.heartbeat()
        self.assertIsNone(active(self.e.state()));self.assertEqual(self.e.state()['wallet'],before);self.assertTrue(all(x==0 for x in self.e.state()['fees_native'].values()))
    def test_new_multi_operations_never_open_or_rewrite_existing_24h_checkpoint(self):
        path=Path(self.tmp.name)/'retained-24h.sqlite3';baseline=IntelligentTrader(path,clock=self.c.wall,monotonic_ns=self.c.ns)
        baseline.start();baseline.review(self.f());baseline.pause();baseline.heartbeat(persist=True);raw=path.read_bytes();original=baseline.state()['original']
        self.e.review(self.f());self.e.pause();self.c.tick(3);self.e.heartbeat(persist=True)
        self.assertEqual(path.read_bytes(),raw);self.assertEqual(baseline.state()['original'],original)
    def test_five_minute_outcome_waits_for_all_reference_timestamps_at_or_after_horizon(self):
        self.e.review(self.f());self.e.pause();self.c.tick(300);self.e.heartbeat();self.e.start();f=self.f()
        for b in f['reference_books'].values():b['at']-=10
        self.e.review(f);self.assertEqual(self.e.state()['horizon_prediction_counts']['M5']['known'],0)
        self.c.tick(10);self.e.review(self.f());self.assertEqual(self.e.state()['horizon_prediction_counts']['M5']['known'],1)
    def test_missing_short_horizon_window_stays_unknown_instead_of_using_later_favorable_quote(self):
        self.e.review(self.f());self.e.pause();self.c.tick(331);self.e.heartbeat();self.e.start();self.e.review(self.f())
        pc=self.e.state()['horizon_prediction_counts']['M5'];self.assertEqual(pc['unknown'],1);self.assertEqual(pc['known'],0)
    def test_detailed_observations_are_lossless_and_fit_the_168_hour_journal_budget(self):
        for i in range(4):self.e.review(self.f());self.c.tick(10)
        events=self.e.store.events();last=events[-1]['payload'];evidence=last['evidence'];detail=decode_observation(evidence['policy_observation'])
        self.assertEqual(detail['horizon_rejection_counts'],self.e.state()['metrics']['rejection_detail'])
        row=self.e.state()['rows'][0]
        self.assertEqual(detail['horizon_review'][row['id']]['M5']['projected_advantage_usd'],row['horizons']['M5']['projected_advantage_usd'])
        self.assertLess(len(pack(last).encode()),24000)
        # 20,160 reviews plus 60,480 observation marks and generous SQLite
        # overhead remain below the unchanged 1 GiB trial-store cap.
        review_bytes=max(len(pack(e['payload']).encode()) for e in events if 'policy_observation' in e['payload'].get('evidence',{}))
        marks=max(len(pack(e['payload']).encode()) for e in events if 'policy_observation' not in e['payload'].get('evidence',{}))
        self.assertLess((review_bytes*20160+marks*60480)*D('1.5'),1024**3)
    def test_observation_decoder_rejects_corruption_and_oversized_decompression(self):
        value=dict(score=D('0.000000000000000000001'),native_fee=D('.0000007064649499'))
        encoded=encode_observation(value);self.assertEqual(decode_observation(encoded),value)
        for change in (dict(sha256='0'*64),dict(data='invalid'),dict(bytes=True),dict(bytes=1048577)):
            with self.subTest(change=change),self.assertRaises(BetaBlocked):decode_observation(dict(encoded,**change))
        bomb=dict(encoded,bytes=1,data=base64.b64encode(zlib.compress(b'x'*1048577)).decode())
        with self.assertRaises(BetaBlocked):decode_observation(bomb)
