"""Deterministic native frames/replay only; all SDK write methods are traps."""
from copy import deepcopy
from dataclasses import replace,asdict
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch
from coincat_beta_store import BetaBlocked,pack
from coincat_trial_clock import NS,TARGET_NS
from coincat_trial_store import TrialStore
from coincat_shadow_trader import ShadowTrader,validate
from coincat_shadow_source import frame_quality,ShadowMarketSource
from coincat_portfolio_policy import PortfolioConfig,select_candidates,performance,usd_marks,assess_ticket,DIRECTIONS
from coincat_order_services import LimitOrderServices,ShadowAuthorization,native_fill_changes,PortfolioInventory
from coincat_spot_market import SpotReader
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS
from offline_tests.test_spot_manual import Venue,cid

class Clock:
    def __init__(self):self.at=1793865600.;self.mono=0
    def wall(self):return self.at
    def monotonic(self):return self.mono/NS
    def ns(self):return self.mono
    def tick(self,s):self.at+=s;self.mono+=round(s*NS)

def account(clock):return dict(portfolio=cid(40),at=clock.wall(),available={a:D(1) if a=='ETH' else D(0) for a in WATCH_ASSETS},holds={a:D(0) for a in WATCH_ASSETS})
def frame(clock,trend=0):
    cross=D('.03')*(D('.999')**trend);mids={'ETH-BTC':cross,'ETH-USD':D(2000),'ADA-ETH':D('.0004'),'LINK-ETH':D('.005'),'SOL-ETH':D('.05')}
    for a in ('ADA','LINK','SOL'):mids[a+'-BTC']=mids[a+'-ETH']*cross
    books={p:dict(pair=p,at=clock.wall(),bid=q*D('.9999'),ask=q*D('1.0001'),bids=((q*D('.9999'),D(100000)),),asks=((q*D('1.0001'),D(100000)),)) for p,q in mids.items()}
    rules={p:dict(product_id=p,product_type='SPOT',status='online',view_only=False,base_increment='.000001',quote_increment='.000000000001',price_increment='.000000000001',base_min_size='.000001',quote_min_size='.000000001') for p in WATCH_PAIRS}
    return dict(state='OBSERVED',at=clock.wall(),portfolio=cid(40),account=account(clock),books=books,rules=rules,tier=dict(at=clock.wall(),maker=D('.005'),taker=D('.009'),source='AUTHENTICATED_ACCOUNT_TIER'))

class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.c=Clock();self.path=Path(self.tmp.name)/'trial.sqlite3'
        self.e=ShadowTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns);self.config=PortfolioConfig()
        self.e.start(account(self.c),self.config)
    def review(self,trend=0):self.e.review(frame(self.c,trend))
    def restart(self,gap=36000,clean=True):
        if clean:self.e.shutdown()
        self.c.tick(gap);self.c.mono=0;self.e=ShadowTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
    def test_clock_and_model_recover_exact_identity_benchmark_and_frozen_caps(self):
        self.review();self.c.tick(20);self.e.heartbeat(persist=True);saved=self.e.state();self.restart()
        self.assertEqual(self.e.progress()['valid_seconds'],20);self.assertEqual(self.e.state()['trial_id'],saved['trial_id'])
        for key in ('wallet','original','config','expires_at','orders'):self.assertEqual(self.e.state()[key],saved[key])
        self.assertEqual(self.e.public()['state'],'RECOVERING');self.review();self.c.tick(10);self.e.heartbeat()
        self.assertEqual(self.e.progress()['valid_seconds'],30);self.assertFalse(self.e.public()['live_permission'])
        with self.assertRaises(BetaBlocked):self.e.start(account(self.c),replace(self.config,max_orders=5))
    def test_six_ten_offline_four_survives_actual_sqlite_checkpoint_and_reload(self):
        from coincat_trial_clock import advance,prime_quality
        trial=self.e.state()['trial_id'];baseline=self.e.state()['original']
        def hours(count):
            state=self.e.store.clock;prime_quality(state,valid=True,coverage=7)
            for i in range(count*120):
                self.c.tick(30);advance(state,wall=self.c.wall(),mono_ns=self.c.ns(),valid=True,coverage=7,run_id=state['run_id'])
                if i%120==119:self.e.store.flush_clock()
        hours(6);self.restart(10*3600);hours(4)
        self.assertEqual(self.e.progress()['valid_seconds'],10*3600)
        self.assertEqual(self.e.progress()['downtime_s'],10*3600)
        self.assertEqual(self.e.state()['trial_id'],trial);self.assertEqual(self.e.state()['original'],baseline)
    def test_atomic_actions_cannot_change_original_benchmark_and_detect_in_process_corruption(self):
        saved=self.e.state()
        with self.assertRaises(BetaBlocked):self.e._change('INVALID_BASELINE',{},lambda s:s['original'].update(ETH=D(2)))
        self.assertEqual(self.e.state(),saved)
        with sqlite3.connect(self.path) as db:db.execute("UPDATE trial_clock SET digest='altered'")
        before=self.path.read_bytes()
        with self.assertRaises(BetaBlocked):self.e.store.flush_clock()
        self.assertEqual(self.path.read_bytes(),before)
    def test_paused_persists_and_disconnected_partial_stale_dont_count(self):
        self.review();self.c.tick(10);self.e.stop();self.restart();self.review();self.c.tick(20);self.e.heartbeat()
        self.assertEqual(self.e.public()['state'],'PAUSED');self.assertEqual(self.e.progress()['valid_seconds'],10)
        self.e.start(account(self.c),self.config);bad=frame(self.c);del bad['books']['ADA-BTC'];self.e.review(bad)
        self.c.tick(20);self.e.heartbeat();self.assertEqual(self.e.progress()['valid_seconds'],10)
        self.c.tick(20);self.e.heartbeat();self.assertEqual(self.e.public()['state'],'DISCONNECTED')
    def test_suspend_cannot_reuse_feed_lease_when_host_monotonic_excludes_sleep(self):
        self.review();self.c.tick(10);self.e.heartbeat();before=self.e.progress()['valid_seconds']
        self.c.at+=3600;self.c.mono+=NS;self.e.heartbeat(persist=True)
        self.assertEqual(self.e.progress()['valid_seconds'],before)
        self.assertEqual(self.e.public()['state'],'DISCONNECTED')
        self.assertTrue(self.e.store.clock['calendar_uncertain'])
    def test_corrupt_missing_or_wrong_checkpoint_never_reset(self):
        self.review();self.e.shutdown();before=self.path.read_bytes()
        with sqlite3.connect(self.path) as db:db.execute("UPDATE trial_clock SET digest='bad'")
        broken=self.path.read_bytes();e=ShadowTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns)
        self.assertEqual(e.public()['state'],'REVIEW_REQUIRED');self.assertEqual(self.path.read_bytes(),broken)
        with self.assertRaises(BetaBlocked):e.start(account(self.c),self.config)
        self.path.write_bytes(before)
        with sqlite3.connect(self.path) as db:db.execute('DROP TABLE trial_clock')
        self.assertTrue(ShadowTrader(self.path,clock=self.c.wall,monotonic_ns=self.c.ns).load_error)
    def test_transaction_duplicate_event_concurrent_clock_and_monotonic_counters(self):
        other=TrialStore(self.path,validate=validate)
        self.e._change('SYNTHETIC',{},lambda s:s.update(reason='ONE'),event_id='stable')
        self.assertEqual(self.e._change('SYNTHETIC',{},lambda s:s.update(reason='TWO'),event_id='stable')['state'],'DUPLICATE_IGNORED')
        with self.assertRaises(BetaBlocked):self.e._change('SYNTHETIC',{'different':True},lambda s:None,event_id='stable')
        with self.assertRaises(BetaBlocked):other.flush_clock()
        self.review();self.c.tick(10);self.e.heartbeat(persist=True)
        self.e.store.clock['valid_ns']=0
        with self.assertRaises(BetaBlocked):self.e.store.flush_clock()
    def test_external_actual_changes_are_excluded_from_simulation_and_hold(self):
        self.review();original=self.e.state()['original'];self.c.tick(30);f=frame(self.c);f['account']['available']['ETH']+=5
        self.e.review(f);s=self.e.state();self.assertEqual(s['wallet'],original);self.assertEqual(s['original'],original)
        self.assertEqual(s['external_changes'][-1]['native_changes']['ETH'],5)
        self.assertEqual(s['last_performance']['outperformance_usd'],0)
    def test_full_trial_completion_preserves_record_and_rejects_new_start(self):
        self.review();self.e.store.clock['valid_ns']=TARGET_NS-10*NS;self.e.store.flush_clock();self.c.tick(10);self.e.heartbeat(persist=True)
        self.assertEqual(self.e.public()['state'],'COMPLETE');self.assertTrue(list(self.path.parent.glob('*summary.json')))
        saved=self.e.state();self.restart();self.assertEqual(self.e.state()['wallet'],saved['wallet'])
        with self.assertRaises(BetaBlocked):self.e.start(account(self.c),self.config)
    def test_trend_policy_proposes_maker_without_quote_fills_and_recovers_proposal(self):
        for i in range(24):self.review(i);self.c.tick(30)
        s=self.e.state();self.assertTrue(s['orders']);o=next(iter(s['orders'].values()))
        self.assertTrue(o['post_only']);self.assertEqual(o['dispatch_count'],0);self.assertEqual(s['fills'],{})
        wallet=deepcopy(s['wallet']);self.restart(clean=False);self.assertEqual(self.e.state()['wallet'],wallet)
        self.assertEqual(self.e.state()['orders'],s['orders']);self.assertEqual(self.e.progress()['interruptions'],1)
    def proposal(self):
        for i in range(24):self.review(i);self.c.tick(30)
        return next(iter(self.e.state()['orders']))
    def event(self,ref,kind,**data):
        return dict(source='EXPLICIT_SIMULATED_REPLAY',reference=ref,kind=kind,at=self.c.wall(),**data)
    def test_partial_cancel_unknown_fee_and_terminal_remaining_identity(self):
        ref=self.proposal();o=self.e.state()['orders'][ref];venue=cid(400)
        self.e.replay(self.event(ref,'DISPATCH'),'d');self.e.replay(self.event(ref,'ACK',venue_id=venue),'a')
        q=o['size']/2;raw=dict(trade_id=cid(401),size=str(q),price=str(o['price']),commission=str(q*o['price']*D('.005')),size_in_quote=False,liquidity_indicator='M')
        event=self.event(ref,'FILL',venue_id=venue,fill=raw);self.e.replay(event,'f')
        self.assertEqual(self.e.state()['mode'],'RECONCILIATION_REQUIRED');self.assertEqual(self.e.state()['wallet'],self.e.state()['original'])
        raw['fee_currency']='BTC';self.e.replay(self.event(ref,'FEE_EVIDENCE',venue_id=venue,fill=raw),'fee')
        self.e.replay(self.event(ref,'CANCEL_ACK',venue_id=venue),'c');self.assertGreater(self.e.state()['orders'][ref]['reserved'],0)
        s=self.e.state();recon=self.event(ref,'RECONCILE',venue_id=venue,fill_ids=[cid(401)],filled_base=q,complete=True,order_hold_released=True,inventory=s['wallet'],status='CANCELED')
        self.e.replay(recon,'r');self.assertEqual(self.e.state()['orders'][ref]['reserved'],0)
        self.assertEqual(self.e.state()['orders'][ref]['filled'],q);saved=self.e.state()['wallet'];self.e.replay(recon,'r');self.assertEqual(self.e.state()['wallet'],saved)
        with self.assertRaises(BetaBlocked):self.e.replay(self.event(ref,'DISPATCH'),'d-again')
    def test_unknown_dispatch_restart_locks_and_never_retries(self):
        ref=self.proposal();self.e.replay(self.event(ref,'DISPATCH'),'d');self.restart(clean=False)
        self.assertEqual(self.e.public()['state'],'REVIEW_REQUIRED');self.assertEqual(self.e.state()['orders'][ref]['dispatch_count'],1)
        with self.assertRaises(BetaBlocked):self.e.start(account(self.c),self.config)
    def test_full_sell_base_fee_uses_buffer_and_never_discards_adverse_cost(self):
        ref=self.proposal();o=self.e.state()['orders'][ref];venue=cid(450)
        self.assertEqual(o['side'],'SELL');self.e.replay(self.event(ref,'DISPATCH'),'d');self.e.replay(self.event(ref,'ACK',venue_id=venue),'a')
        fee=o['size']*D('.03') # Deliberately exceeds the frozen 2% ceiling.
        raw=dict(trade_id=cid(451),size=str(o['size']),price=str(o['price']),commission=str(fee),fee_currency='ETH',size_in_quote=False,liquidity_indicator='M')
        self.e.replay(self.event(ref,'FILL',venue_id=venue,fill=raw),'cost')
        s=self.e.state();self.assertEqual(s['wallet']['ETH'],D(1)-o['size']-fee)
        self.assertTrue(s['orders'][ref]['budget_breach']);self.assertEqual(s['mode'],'RECONCILIATION_REQUIRED')
        self.assertTrue(s['fills'][cid(451)]['settled']);self.assertEqual(s['fills'][cid(451)]['flow']['commission'],fee)
    def test_missing_sized_depth_blocks_entries_without_a_fake_fill(self):
        for i in range(24):
            f=frame(self.c,i)
            for b in f['books'].values():b['bids']=((b['bid'],D('0.000000001')),);b['asks']=((b['ask'],D('0.000000001')),)
            self.e.review(f);self.c.tick(30)
        self.assertEqual(self.e.state()['orders'],{});self.assertEqual(self.e.state()['fills'],{})
    def test_original_expiry_and_attempt_budget_not_reset(self):
        ref=self.proposal();expires=self.e.state()['expires_at'];self.restart(31*86400)
        self.review();self.assertEqual(self.e.state()['expires_at'],expires);self.assertLessEqual(len(self.e.state()['orders']),4)
        self.assertIn(self.e.state()['reason'],('HOLD_COSTS_UNCERTAINTY_OR_RISK_NOT_JUSTIFIED','WAIT_CANCEL_QUANTITY_AND_HOLDS','NO_NEW_INTENTS_ORIGINAL_EXPIRY_OR_CLOCK_UNCERTAINTY'))

class PolicyServices(unittest.TestCase):
    def test_fourteen_views_warmup_wide_and_native_minimums(self):
        c=Clock();f=frame(c);wallet=account(c)['available'];rows,chosen=select_candidates(f,wallet,wallet,wallet,[],PortfolioConfig())
        self.assertEqual(len(rows),14);self.assertIsNone(chosen)
        self.assertTrue(frame_quality(f)[0]);f['books']['ADA-BTC']['ask']*=2
        self.assertTrue(frame_quality(f)[0]) # Accurate wide quotes can justify HOLD and still be observed.
        del f['books']['ADA-BTC'];self.assertEqual(frame_quality(f),(False,6))
    def test_hold_benchmark_uses_all_original_assets_and_market_appreciation_not_edge(self):
        c=Clock();f=frame(c);wallet={a:D(1) for a in WATCH_ASSETS};p=performance(f,wallet,wallet,[],PortfolioConfig(),initial_usd=D(10))
        self.assertEqual(p['outperformance_usd'],0);self.assertGreater(p['change_usd'],0)
        self.assertEqual(set(p['open_inventory']),set(WATCH_ASSETS));self.assertIsNone(p['liquidation_usd'])
    def test_all_fourteen_directions_reject_untradable_native_rules(self):
        c=Clock();f=frame(c);marks,_=usd_marks(f);wallet={a:D(1) for a in WATCH_ASSETS}
        observations=[dict(at=c.wall()-30*(20-i),marks=marks) for i in range(21)]
        for view in DIRECTIONS:
            bad=deepcopy(f);bad['rules'][view['pair']]['view_only']=True
            rows,_=select_candidates(bad,wallet,wallet,wallet,observations,PortfolioConfig())
            row=next(r for r in rows if r['id']==view['id'])
            with self.subTest(view=view['id']):
                self.assertEqual(row['state'],'HOLD');self.assertEqual(row['reason'],'PRODUCT_NOT_TRADABLE_WITH_THIS_ACCOUNT')
    def test_shadow_cannot_receive_manual_create_grant(self):
        class Trap:
            def __getattr__(self,name):raise AssertionError('SDK must never be reached')
        service=LimitOrderServices(lambda:Trap(),manual_guard=lambda x:True,owned_guard=lambda c,o:False,clock=lambda:1)
        with self.assertRaisesRegex(BetaBlocked,'AUTOMATIC_LIVE'):service.create({},cid(),ShadowAuthorization())
        with self.assertRaises(BetaBlocked):service.cancel_owned(dict(cid=cid(),order_id=cid(1)))
    def test_native_quote_base_and_third_asset_fees_once(self):
        raw=dict(product_id='ETH-BTC',side='SELL',size='.005',price='.03',commission='.000001',size_in_quote=False)
        with self.assertRaises(BetaBlocked):native_fill_changes(raw)
        for asset in ('BTC','ETH','ADA'):
            changes=native_fill_changes(dict(raw,fee_currency=asset))['changes'];expected={a:D(0) for a in WATCH_ASSETS}
            expected['ETH']=-D('.005');expected['BTC']=D('.00015');expected[asset]-=D('.000001');self.assertEqual(changes,expected)
    def test_read_only_source_reads_all_seven_and_reference_with_bounded_calls(self):
        c=Clock();v=Venue(c);reader=SpotReader(v,clock=c.wall,monotonic=c.monotonic,budget=None);src=ShadowMarketSource(reader)
        self.assertEqual(src.collect()['state'],'PRIMING');self.assertLessEqual(reader.calls,16)
        f=src.collect();self.assertEqual(f['native_book_count'],7);self.assertEqual(len(f['books']),8);self.assertLessEqual(reader.calls,16)
        self.assertEqual(v.posts,[]);self.assertEqual(v.cancels,[])
