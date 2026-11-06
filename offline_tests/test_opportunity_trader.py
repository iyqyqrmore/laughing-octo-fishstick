"""Native fees, resting-order lifecycle and restart tests without a live client."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from coincat_beta_store import BetaBlocked
from coincat_opportunity_policy import OpportunityConfig
from coincat_opportunity_trader import OpportunityTrader,active
from coincat_opportunity_public import validate as validate_public
from coincat_trial_clock import NS,TARGET_NS
from offline_tests.test_resumable_trial import Clock
from offline_tests.test_opportunity_policy import market

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.c=Clock();self.path=Path(self.tmp.name)/'opportunity.sqlite3'
        self.e=OpportunityTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns);self.e.start();self.step=0;self.prints=[]
    def f(self,step=None,*,anchor=True):
        f=market(self.c,self.step if step is None else step)
        pair=self.e.current_pair()
        if pair is not None and anchor:f['market_trades']=dict(pair=pair,at=self.c.wall(),prints=deepcopy(self.prints),source='COINBASE_AUTH_MARKET_TRADES')
        return f
    def warm(self,config=None):
        if config is not None:self.e.pending_config=config
        for i in range(61):self.step=i//3;self.e.review(self.f());self.c.tick(10)
        self.assertIsNotNone(active(self.e.state()));return active(self.e.state())
    def acknowledge(self):
        o=active(self.e.state());self.prints=[dict(id='anchor',price=o['price'],size=D('.000001'),at=self.c.wall())]
        self.e.review(self.f());return active(self.e.state())
    def fill(self,o,size=None,*,fee=None,currency=None,trade='replay-fill'):
        q=o['size'] if size is None else size;commission=q*o['price']*D('.005') if fee is None else fee
        raw=dict(trade_id=trade,product_id=o['pair'],side=o['side'],size=q,price=o['price'],commission=commission,
            fee_currency=o['pair'].split('-')[1] if currency is None else currency,size_in_quote=False,liquidity_indicator='M')
        event=dict(source='EXPLICIT_SIMULATED_REPLAY',reference=o['reference'],kind='FILL',at=self.c.wall(),receipt=raw)
        self.e.replay(event,'replay-'+trade);return event
    def test_warmup_and_new_order_reserve_do_not_charge_a_future_or_executed_fee(self):
        o=self.warm();s=self.e.state();self.assertEqual(o['state'],'NEW');self.assertEqual(s['wallet'],s['original'])
        self.assertTrue(all(v==0 for v in s['fees_native'].values()));self.assertGreater(o['projection']['projected_advantage_usd'],0)
        self.assertEqual(s['metrics']['fill_events'],0);self.assertEqual(s['metrics']['orders'],1)
    def test_quote_and_trade_price_touches_never_guarantee_a_maker_fill(self):
        self.warm();o=self.acknowledge()
        for i in range(1,9):
            self.c.tick(10);self.prints.append(dict(id='touch'+str(i),price=o['price'],size=D(1000000),at=self.c.wall()))
            self.e.review(self.f())
        s=self.e.state();self.assertEqual(s['metrics']['fill_events'],0);self.assertEqual(s['wallet'],s['original'])
    def test_public_strict_trade_through_requires_rest_continuity_volume_and_multiple_samples(self):
        self.warm();o=self.acknowledge();before=deepcopy(self.e.state()['wallet'])
        for i in range(1,4):
            self.c.tick(10);self.prints.append(dict(id='through'+str(i),price=o['price']+D('.000000000001'),size=D('.001'),at=self.c.wall()))
            self.e.review(self.f())
            if i<3:self.assertEqual(self.e.state()['metrics']['fill_events'],0)
        s=self.e.state();self.assertEqual(s['metrics']['modeled_fills'],1);self.assertNotEqual(s['wallet'],before)
        self.assertGreater(s['fees_native']['BTC'],0);self.assertIsNotNone(s['metrics']['last_fill_change_usd'])
    def test_replay_charges_native_commission_exactly_once_and_retains_negative_fill_mark(self):
        self.warm();o=self.acknowledge();old=deepcopy(self.e.state()['wallet']);event=self.fill(o)
        s=self.e.state();self.assertEqual(s['wallet']['ETH'],old['ETH']-o['size'])
        self.assertEqual(s['wallet']['BTC'],old['BTC']+o['size']*o['price']-event['receipt']['commission'])
        self.assertEqual(s['fees_native']['BTC'],event['receipt']['commission']);self.assertLess(s['metrics']['last_fill_change_usd'],0)
        saved=self.e.state();self.e.replay(event,'replay-replay-fill');self.assertEqual(self.e.state(),saved)
    def test_cancel_then_reprice_waits_for_reconciled_partial_and_never_reuses_filled_quantity(self):
        config=replace(OpportunityConfig(),size_percent={p:D(5) if p=='ETH-BTC' else D(0) for p in OpportunityConfig().size_percent})
        self.warm(config);o=self.acknowledge();q=o['size']/2
        # Use an exact native partial increment.
        inc=D(o['rules']['base_increment']);q=(q//inc)*inc;self.assertGreater(q,0);self.fill(o,q)
        for i in range(1,18):self.c.tick(10);self.step=20+i//3;self.e.review(self.f())
        orders=list(self.e.state()['orders'].values());parent=orders[0]
        self.assertEqual(parent['filled'],q);self.assertEqual(parent['state'],'CANCELED');self.assertEqual(parent['reserved'],0)
        children=[child for child in orders[1:] if child['campaign']==parent['campaign']]
        self.assertEqual(len(children),1)
        for child in children:
            self.assertEqual(child['size'],parent['size']-q);self.assertGreaterEqual(child['created_at'],parent['closed_at'])
    def test_finite_lifetime_cancels_even_without_quotes_and_no_losing_liquidation_occurs(self):
        self.warm();o=self.acknowledge();wallet=deepcopy(self.e.state()['wallet'])
        self.c.tick(601);self.e.heartbeat(persist=True);self.assertEqual(active(self.e.state())['state'],'CANCEL_PENDING')
        self.c.tick(3);self.e.heartbeat(persist=True)
        self.assertIsNone(active(self.e.state()));self.assertEqual(self.e.state()['wallet'],wallet)
        self.assertEqual(self.e.state()['metrics']['nonfills'],1);self.assertTrue(all(v==0 for v in self.e.state()['fees_native'].values()))
    def test_retry_budget_and_original_campaign_budget_expiry_never_reset(self):
        config=replace(OpportunityConfig(),retry_budget=0);self.warm(config);self.acknowledge()
        root0=deepcopy(next(iter(self.e.state()['campaigns'].values())))
        for i in range(75):self.c.tick(10);self.step=21+i//3;self.e.review(self.f())
        roots=list(self.e.state()['campaigns'].values());self.assertEqual(roots[0]['budget'],root0['budget']);self.assertEqual(roots[0]['expires_at'],root0['expires_at'])
        self.assertEqual(roots[0]['attempts'],1);self.assertEqual(self.e.state()['metrics']['replacements'],0)
    def test_unknown_outcome_blocks_replacement_until_exact_inventory_and_hold_reconciliation(self):
        self.warm();o=self.acknowledge();event=dict(source='EXPLICIT_SIMULATED_REPLAY',kind='UNKNOWN',reference=o['reference'],at=self.c.wall())
        self.e.replay(event,'unknown');self.assertFalse(self.e.running);self.assertEqual(active(self.e.state())['state'],'UNKNOWN')
        self.c.tick(2000);self.e.heartbeat(persist=True);self.assertEqual(active(self.e.state())['state'],'UNKNOWN')
        with self.assertRaises(BetaBlocked):self.e.start()
        s=self.e.state();recon=dict(source='EXPLICIT_SIMULATED_REPLAY',kind='RECONCILE',reference=o['reference'],at=self.c.wall(),status='CANCELED',filled=D(0),inventory=s['wallet'],held_source=D(0),complete=True)
        self.e.replay(recon,'recon');self.assertIsNone(active(self.e.state()));self.assertEqual(self.e.state()['wallet'],s['wallet'])
    def test_restart_keeps_wallet_original_fees_hours_and_cancels_owned_order_before_new_entry(self):
        self.warm();o=self.acknowledge();saved=self.e.state();hours=self.e.progress()['valid_seconds'];self.e.shutdown();self.c.tick(3600)
        restored=OpportunityTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertFalse(restored.load_error);self.assertTrue(restored.running);self.assertEqual(restored.state()['wallet'],saved['wallet']);self.assertEqual(restored.state()['original'],saved['original'])
        self.assertEqual(restored.progress()['valid_seconds'],hours);self.assertEqual(active(restored.state())['state'],'UNKNOWN')
        restored.heartbeat();self.c.tick(3);restored.heartbeat();self.assertIsNone(active(restored.state()))
        self.assertEqual(restored.state()['metrics']['fill_events'],0)
    def test_public_status_excludes_financial_details_and_marks_forecast_and_fills_as_unvalidated(self):
        self.warm();value=validate_public(self.e.public());self.assertFalse(value['live_permission'])
        self.assertEqual(value['profit'],'NOT_ESTABLISHED');self.assertEqual(value['fill_evidence'],'CONDITIONAL_NOT_CALIBRATED')
        for key in ('wallet','projected_advantage_usd','fee_currency','reference'):
            bad=deepcopy(value);bad[key]='private'
            with self.subTest(key=key),self.assertRaises(ValueError):validate_public(bad)
