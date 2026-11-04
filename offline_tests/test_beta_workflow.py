"""End-to-end synthetic lifecycle and actual Tk bindings, never real HTTP/WS."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch,Mock

from coincat_live import LiveBroker,LiveBlocked
from coincat_live_beta import LiveBeta,LiveLimits
from coincat_beta_controller import LiveCoordinator
from coincat_beta_store import BetaBlocked
from coincat_global_paper import GlobalSettings
from coincat_monitor import capture,encode,validate
from coincat_simple_diagnostics import make_report
from offline_tests import gui_fixtures as gui
from offline_tests import test_live_beta as live_test
from offline_tests import test_global_paper as g
from offline_tests.test_beta_evidence import ReadVenue,native_record


class ManagedVenue(live_test.Venue):
    def __init__(self,frame):super().__init__(frame);self.actual=None;self.fills=[];self.foreign_cancel=False
    def get_order(self,order_id):
        value=deepcopy(self.actual) if self.actual is not None else super().get_order(order_id)['order']
        if self.foreign_cancel:value['client_order_id']=live_test.TID
        return {'order':value}
    def get_fills(self,**kwargs):return {'fills':deepcopy(self.fills),'cursor':''}
    def list_orders(self,**kwargs):return {'orders':[],'has_next':False}
    def get_accounts(self,**kwargs):
        return {'accounts':[dict(uuid='00000000-0000-0000-0000-000000000009',retail_portfolio_id=live_test.PORTFOLIO,
            currency='ETH',available_balance={'value':'1'},hold={'value':'0'})],'has_next':False}


class LiveWorkflow(unittest.TestCase):
    def setUp(self):
        self.case=live_test.LiveBetaGate('runTest');self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.engine=self.case.engine;self.clock=self.case.clock;self.case.funded()
        self.venue=ManagedVenue(self.case.frame);self.coordinator=LiveCoordinator(self.engine);self.coordinator.bind(self.venue)
        self.cid=self.case.prepare();self.coordinator.broker.submit(live_dispatch=self.cid)

    def test_timeout_uses_monotonic_acceptance_119_9_retains_120_cancels_and_fill_race_settles_once(self):
        self.clock.tick(119.9);order=self.engine.private_state()['orders'][self.cid]
        self.assertFalse(self.coordinator._cancel_due(order,None));self.clock.tick(.1)
        self.assertTrue(self.coordinator._cancel_due(order,None));self.coordinator.cycle()
        self.assertEqual(len(self.venue.cancel_posts),1);self.assertEqual(self.engine.private_state()['orders'][self.cid]['state'],'CANCEL_PENDING')
        self.assertEqual(self.engine.private_state()['orders'][self.cid]['reserved'],D('.00408612'))
        self.venue.actual,self.venue.fills=self.case.receipt(self.cid)
        self.coordinator.cycle();state=self.engine.private_state()
        self.assertEqual(state['orders'][self.cid]['state'],'FILLED');self.assertEqual(len(state['fills']),1)
        self.coordinator.cycle();self.assertEqual(self.engine.private_state()['wallet'],state['wallet']);self.assertEqual(len(self.venue.posts),1)

    def test_reblock_cancels_only_owned_identity_and_never_releases_on_ack(self):
        self.engine.set_blocked(True);self.coordinator.cycle()
        self.assertEqual(len(self.venue.cancel_posts),1);self.assertEqual(self.engine.available('ETH'),0)
        self.engine.set_blocked(False)
        with self.assertRaises(BetaBlocked):self.engine.start()
        self.assertEqual(len(self.venue.posts),1)
        self.venue.foreign_cancel=True;self.clock.tick(30)
        with self.assertRaises(LiveBlocked):self.coordinator.broker.cancel_live_beta(self.cid)
        self.assertEqual(len(self.venue.cancel_posts),1);self.assertEqual(self.engine.private_state()['mode'],'UNKNOWN_LOCKED')

    def test_higher_profit_floor_never_rewrites_fixed_order_and_requires_safe_cancel(self):
        original=self.engine.private_state()['orders'][self.cid]
        self.engine.apply_settings(GlobalSettings(min_net_usd=D(1)))
        self.clock.tick(30)
        frame=live_test.profitable_frame(self.clock.at);self.engine.last_reference=g.usd(frame.at)
        self.assertTrue(self.coordinator._cancel_due(original,frame))
        order=self.engine.private_state()['orders'][self.cid]
        self.assertEqual(order['limit_price'],original['limit_price']);self.assertEqual(order['global_policy_version'],1)
        self.assertEqual(order['reserved'],original['reserved'])

    def test_pause_and_backward_wall_clock_cannot_extend_original_process_deadline(self):
        # Terminal no-fill receipt releases the child, not the original clock.
        actual=self.venue.get_order(live_test.OID)['order'];actual['status']='CANCELED'
        self.engine.reconcile_order(self.cid,actual,[],complete=True);deadline=self.engine.deadline_mono
        self.engine.set_blocked(True);self.clock.tick(100);self.clock.at-=50
        self.engine.set_blocked(False);self.engine.start()
        self.assertEqual(self.engine.deadline_mono,deadline)

    def test_external_inventory_consumption_locks_owned_amount_instead_of_shrinking(self):
        actual=self.venue.get_order(live_test.OID)['order'];actual['status']='CANCELED';self.engine.reconcile_order(self.cid,actual,[],complete=True)
        self.clock.tick(30);frame=live_test.profitable_frame(self.clock.at)
        result=self.engine.prepare(frame,g.usd(frame.at),account=dict(at=frame.at,portfolio=live_test.PORTFOLIO,available={'ETH':D('.001')},carveouts={}))
        self.assertIsNone(result);self.assertEqual(self.engine.private_state()['mode'],'UNKNOWN_LOCKED')
        self.assertEqual(self.engine.private_state()['wallet'],{'ETH':D('.00408612')});self.assertEqual(len(self.venue.posts),1)

    def test_missing_recovered_identity_never_reposts_after_restart(self):
        self.engine._change('SYNTHETIC_UNKNOWN',{},lambda s:s['orders'][self.cid].update(order_id=None,state='UNKNOWN'))
        restored=LiveBeta(self.engine.directory,clock=self.clock.wall,monotonic=self.clock.monotonic)
        controller=LiveCoordinator(restored);controller.bind(self.venue);controller.cycle(reconcile=True)
        self.assertTrue(restored.blocked.is_set());self.assertEqual(restored.private_state()['orders'][self.cid]['reserved'],D('.00408612'))
        self.assertEqual(len(self.venue.posts),1)

    def test_explicit_reconciliation_rechecks_terminal_fee_corrections_and_cannot_clear_review(self):
        self.venue.actual,self.venue.fills=self.case.receipt(self.cid);self.coordinator.cycle()
        before=self.engine.private_state()['wallet'];self.assertEqual(self.engine.private_state()['orders'][self.cid]['state'],'FILLED')
        changed=str(D(self.venue.fills[0]['commission'])+D('.000000001'))
        self.venue.fills[0]['commission']=changed;self.venue.actual['total_fees']=changed
        self.coordinator.cycle(reconcile=True)
        self.assertEqual(self.engine.private_state()['mode'],'UNKNOWN_LOCKED');self.assertEqual(self.engine.public()['unresolved'],1)
        self.assertEqual(self.engine.private_state()['wallet'],before);self.assertTrue(self.engine.blocked.is_set())

    def test_failed_owned_order_reads_back_off_and_exhaust_without_retrying_post(self):
        with patch.object(self.venue,'get_api_key_permissions',side_effect=TimeoutError('SYNTHETIC')) as read:
            self.engine.set_blocked(True)
            for attempt in range(5):
                self.coordinator.cycle();self.assertEqual(read.call_count,attempt+1)
                self.coordinator.cycle();self.assertEqual(read.call_count,attempt+1)
                self.clock.tick(61)
            self.assertFalse(self.coordinator.needs_poll());self.coordinator.cycle();self.assertEqual(read.call_count,5)
            self.coordinator.cycle(reconcile=True);self.assertEqual(read.call_count,6)
        self.assertEqual(len(self.venue.posts),1);self.assertGreater(self.engine.private_state()['orders'][self.cid]['reserved'],0)


class BetaGUI(gui.SimpleGUI):
    legacy_workspace=False
    def settle_worker(self,timeout=5):
        end=time.monotonic()+timeout
        while self.app.busy and time.monotonic()<end:self.root.update();time.sleep(.005)
        self.assertFalse(self.app.busy,'bounded synthetic worker did not return');self.root.update_idletasks()

    def test_default_gate_switch_and_limits_never_start_or_seed_automatically(self):
        app=self.app;self.assertTrue(app.live_orders_blocked.get());self.assertTrue(app.live.blocked.is_set())
        self.assertFalse(app.book_enabled.get());self.assertFalse(app.book_provider_enabled.get())
        app._apply_live_limits();self.assertEqual(app.live_limits_applied.max_eth,D('.005'));self.assertIsNone(app.live.store)
        app.live_orders_blocked.set(False);app._live_switch_changed();self.assertFalse(app.live.blocked.is_set())
        self.assertIn('REAL',app.paper_panel.start_button['text']);self.assertFalse(app.running);self.assertIsNone(app.live.store)
        app._stop();self.assertTrue(app.live_orders_blocked.get());self.assertIn('Paper',app.paper_panel.start_button['text'])

    def test_all_market_books_keep_both_sides_visible_at_minimum_window_without_network(self):
        app=self.app;panel=app.paper_panel;self.root.geometry('1040x780')
        from offline_tests.test_beta_evidence import packet,iso
        now=int(time.time());app.scanner=SimpleNamespace(account_at=now,rules={p:dict(price_increment='.000001') for p in panel.pages})
        for pair,page in panel.pages.items():
            panel.market_tabs.select(page);self.root.update()
            gen=app.book_hub.begin((pair,));app.book_hub.apply(packet(0,pair,at=now),generation=gen,at=now)
            app.book_hub.apply(dict(channel='heartbeats',timestamp=iso(now),events=[dict(current_time=iso(now),heartbeat_counter=1)]),generation=gen,at=now)
            page.order_book.refresh(rules=app.scanner.rules[pair],at=now);self.root.update_idletasks()
            self.assertEqual(len(page.book_trees['Bid'].get_children()),2)
            self.assertEqual(page.book_trees['Ask']['height'],3);self.assertEqual(page.book_trees['Bid']['height'],3)
            viewport=page.order_book.master
            self.assertLessEqual(page.book_trees['Bid'].winfo_rooty()+page.book_trees['Bid'].winfo_height(),viewport.winfo_rooty()+viewport.winfo_height())
        self.assertFalse(app.book_stream.alive());self.assertIsNone(app.live.store);self.assertIsNone(app.paper.engine)

    def test_manual_tab_selection_does_not_import_and_explicit_view_only_import_has_no_bot_credit(self):
        app=self.app;venue=ReadVenue();app.scanner=SimpleNamespace(client=venue,account_at=time.time(),rules={})
        self.assertEqual(app.manual_store.records(),[])
        app.tabs.select(app.tabs.tabs()[-1]);app.archive_tabs.select(app.manual_panel.master);self.root.update()
        self.assertFalse(app.busy);self.assertEqual(venue.calls,[])
        app._manual_import(order_id=live_test.OID);self.settle_worker()
        self.assertEqual(len(app.manual_store.records()),1);self.assertEqual(app.live_public['fills'],0);self.assertIsNone(app.paper.engine)
        self.assertEqual(app.manual_public['known_native_flow'],1)

    def test_enabled_start_and_current_scan_reach_real_adapter_then_stop_cancels_owned_order(self):
        app=self.app;now=time.time();venue=ManagedVenue(live_test.profitable_frame(now))
        app.scanner=SimpleNamespace(client=venue,account_at=now,rules=venue.frame._rules,balances={'ETH':D(1)},catalog=venue.frame._catalog)
        app.connected=True;app.allocation_editor.snapshot({'ETH':D(1)},now,now,())
        app.paper_panel.apply_global_settings();app.live_limit_values['max_eth'].set('.00408612');app._apply_live_limits()
        app.live_orders_blocked.set(False);app._live_switch_changed()
        with patch.object(app,'_scan'):
            app._start_auto_trader();self.settle_worker()
            self.assertTrue(app.live_observe);self.assertTrue(app.running);self.assertEqual(venue.posts,[])
            frame=live_test.profitable_frame(time.time());venue.frame=frame
            app._queue_live_frame(frame,g.usd(frame.at));self.settle_worker()
        self.assertEqual(len(venue.posts),1);self.assertEqual(app.live_public['orders'],1)
        app._stop();self.assertTrue(app.live.blocked.is_set());app._beta_tick();self.settle_worker()
        self.assertEqual(len(venue.cancel_posts),1);self.assertEqual(app.live.available('ETH'),0)
        self.assertEqual(len(venue.posts),1);self.assertIsNone(app.paper.engine)

    def test_diagnostics_monitor_quantity_free_beta_counts_and_unknown_nested_fields_rejected(self):
        app=self.app;private='9876543.210987654321'
        app.live_public.update(blocked=False,state='ACTIVE',orders=2,fills=1,order_id=live_test.OID,balance=private)
        app.manual_public.update(fee_amount=private);app.book_public.update(price=private)
        snap=capture(app,session='b'*32,sequence=1);raw=encode(snap).decode();report=make_report(app)
        self.assertNotIn(private,raw+report);self.assertNotIn(live_test.OID,raw+report)
        self.assertEqual(snap['beta']['live']['fills'],1);self.assertIn('BOUNDED_REAL_BETA_ENABLED',report)
        bad=deepcopy(snap);bad['beta']['manual']['order_id']=live_test.OID
        with self.assertRaises(ValueError):validate(bad)
