from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from coincat_intelligent_trader import IntelligentTrader
from coincat_intelligent_policy import IntelligentConfig
from coincat_maker_shadow import active
from coincat_beta_store import BetaBlocked
from coincat_trial_clock import NS,TARGET_NS
from offline_tests.intelligent_fixtures import Clock,history,frame

class IntelligentExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c=Clock();cls.hist=history(c);cls.initial=frame(c,cls.hist)
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.c=Clock();self.path=Path(self.tmp.name)/'intelligent.sqlite3'
        self.e=IntelligentTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns);self.e.start();self.prints=[]
    def f(self):
        f=frame(self.c,self.hist,prediction=self.initial['forecast']);f['forecast'].update(decision_at=self.c.wall(),forecast_end_at=self.c.wall()+86400)
        pair=self.e.current_pair()
        if pair:f['market_trades']=dict(pair=pair,at=self.c.wall(),prints=deepcopy(self.prints))
        return f
    def order(self):
        self.e.review(self.f());o=active(self.e.state());self.assertIsNotNone(o)
        self.c.tick(10);self.prints=[dict(id='anchor',price=o['price'],size=D('.1'),at=self.c.wall())];self.e.review(self.f())
        return active(self.e.state())
    def fill(self,o,q=None,*,trade='test-fill',unknown=False):
        q=o['size'] if q is None else q;fee=q*o['price']*D('.005')
        receipt=dict(trade_id=trade,product_id=o['pair'],side=o['side'],size=q,price=o['price'],size_in_quote=False,
            commission=fee,liquidity_indicator='M')
        if not unknown:receipt['fee_currency']=o['pair'].split('-')[1]
        event=dict(source='EXPLICIT_SIMULATED_REPLAY',reference=o['reference'],kind='FILL',receipt=receipt,at=self.c.wall())
        self.e.replay(event,'event-'+trade);return event
    def test_native_entry_fee_charged_once_only_after_a_fill_and_negative_mark_stays_visible(self):
        o=self.order();before=self.e.state();self.assertEqual(before['fees_native'],dict.fromkeys(before['wallet'],D(0)))
        event=self.fill(o);after=self.e.state();quote=o['pair'].split('-')[1]
        self.assertEqual(after['fees_native'][quote],event['receipt']['commission']);self.assertLess(after['metrics']['last_fill_change_usd'],0)
        self.e.replay(event,'event-test-fill');self.assertEqual(self.e.state(),after)
        self.assertEqual(after['original'],before['original']);self.assertEqual(after['strategy'],'INTELLIGENT_ONE_LEG_24H_V1')
    def test_quote_touches_and_time_never_fill_and_finite_expiry_cancels_without_a_fee(self):
        o=self.order();before=deepcopy(self.e.state()['wallet'])
        for i in range(4):
            self.c.tick(10);self.prints.append(dict(id='touch'+str(i),price=o['price'],size=D(100),at=self.c.wall()));self.e.review(self.f())
        self.assertEqual(self.e.state()['metrics']['fill_events'],0)
        self.c.tick(601);self.e.heartbeat(persist=True);self.c.tick(3);self.e.heartbeat(persist=True)
        self.assertIsNone(active(self.e.state()));self.assertEqual(self.e.state()['wallet'],before);self.assertEqual(self.e.state()['metrics']['nonfills'],1)
    def test_partial_cancel_race_charges_only_filled_quantity_and_preserves_residual_inventory(self):
        o=self.order();inc=D(o['rules']['base_increment']);q=(o['size']/2//inc)*inc;self.assertGreater(q,0)
        self.e.pause();self.fill(o,q);self.assertEqual(active(self.e.state())['filled'],q)
        self.c.tick(3);self.e.heartbeat(persist=True);s=self.e.state();self.assertIsNone(active(s))
        self.assertEqual(s['orders'][o['reference']]['state'],'CANCELED');self.assertEqual(s['metrics']['fill_events'],1)
        self.assertEqual(s['fees_native'][o['pair'].split('-')[1]],q*o['price']*D('.005'))
    def test_unknown_commission_never_credits_destination_or_retries_and_survives_restart(self):
        o=self.order();before=self.e.state()['wallet'];self.fill(o,unknown=True)
        self.assertEqual(self.e.state()['wallet'],before);self.assertEqual(self.e.state()['mode'],'REVIEW_REQUIRED')
        self.e.shutdown();self.c.tick(3600);restored=IntelligentTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertFalse(restored.load_error);self.assertFalse(restored.running);self.assertEqual(active(restored.state())['state'],'UNKNOWN')
        with self.assertRaises(BetaBlocked):restored.start()
    def test_restart_preserves_original_wallet_fees_hours_and_cancels_before_new_decision(self):
        o=self.order();self.c.tick(10);self.e.heartbeat(persist=True);valid=self.e.progress()['valid_seconds'];saved=self.e.state()
        self.e.shutdown();self.c.tick(7200);restored=IntelligentTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertFalse(restored.load_error);self.assertEqual(restored.progress()['valid_seconds'],valid)
        for key in ('original','wallet','fees_native','trial_id','config'):self.assertEqual(restored.state()[key],saved[key])
        restored.heartbeat();self.c.tick(3);restored.heartbeat();self.assertIsNone(active(restored.state()));self.assertEqual(restored.state()['metrics']['fill_events'],0)
    def test_zero_trade_168_hours_completes_and_report_is_frozen(self):
        f=self.f();f['forecast']=dict(state='HOLD',reason='FORECAST_HISTORY_INSUFFICIENT');self.e.review(f)
        self.e.store.clock['valid_ns']=TARGET_NS-10*NS;self.e.store.flush_clock();self.c.tick(10);self.e.heartbeat(persist=True)
        self.assertEqual(self.e.state()['mode'],'COMPLETE');saved=self.e.state();self.assertEqual(saved['metrics']['orders'],0)
        path=self.e.write_report();content=path.read_bytes();self.e.shutdown();self.c.tick(3600)
        restored=IntelligentTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns);restored.heartbeat()
        self.assertEqual(restored.state(),saved);self.assertEqual(path.read_bytes(),content)
        with self.assertRaises(BetaBlocked):restored.start()
