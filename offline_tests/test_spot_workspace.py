"""Real Tk controls with fake venue events; offline, no private installation."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from coincat_spot_app import SpotApp
from coincat_spot_public import diagnostic,validate
from coincat_monitor import capture,encode
from offline_tests.test_spot_manual import Venue,Clock,cid


class ManualWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.clock=Clock();self.venue=Venue(self.clock)
        self.root=tk.Tk();self.errors=[];self.root.report_callback_exception=lambda c,e,t:self.errors.append(str(e))
        self.root.tk.createcommand('bgerror',lambda e:self.errors.append(str(e)))
        self.app=SpotApp(self.root,data=self.tmp.name,client=self.venue,clock=self.clock.wall)
        self.root.update_idletasks();self.addCleanup(self.finish)
    def pump(self,predicate,seconds=5):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:self.root.update();time.sleep(.005)
        self.assertTrue(predicate(),'bounded worker did not finish');self.root.update_idletasks()
    def finish(self):
        if not self.app.closed:self.app.close();self.pump(lambda:self.app.closed)
        self.root.tk.call('update','idletasks');self.assertEqual(self.errors,[])
    def connect(self):self.app.connect();self.pump(lambda:self.app.connected and not self.app.busy)
    def resize(self,width,height):
        # Win32 delivers the native resize through the event queue. Idle work
        # alone can leave descendants at the preceding 1450px geometry.
        self.root.geometry(str(width)+'x'+str(height));deadline=time.monotonic()+5
        previous=None;stable=0
        while time.monotonic()<deadline:
            self.root.update();p=self.app.panel()
            widgets=(p.book_tree,p.trade_button,p.size_entry,p.price_entry,self.app.balance_tree)
            actual=(self.root.winfo_width(),self.root.winfo_height())
            sample=tuple((w.winfo_rootx(),w.winfo_rooty(),w.winfo_width(),w.winfo_height()) for w in widgets)
            if actual==(width,height):
                stable=stable+1 if sample==previous else 0
                if stable>=2:return
            else:stable=0
            previous=sample;time.sleep(.005)
        self.fail('Native resize did not settle: requested '+str((width,height))+
            ', actual '+str((self.root.winfo_width(),self.root.winfo_height()))+
            ', Tk scaling '+str(self.root.tk.call('tk','scaling')))
    def test_default_entry_has_seven_market_tabs_dropdown_star_and_no_automatic_controller(self):
        self.assertEqual(len(self.app.tabs.tabs()),7);self.assertEqual(self.app.market.get(),'ETH-BTC')
        self.assertTrue(self.app.blocked.get());self.assertFalse(hasattr(self.app,'live_coordinator'));self.assertFalse(hasattr(self.app,'paper'))
        self.app.toggle_favorite();self.assertIn('ETH-BTC',self.app.favorites)
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_native_book_units_and_ask_ticket_without_invented_fills(self):
        self.connect();p=self.app.panel();p.use_price('ASK');self.assertEqual(p.price.get(),'0.030010')
        p.size.set('.001');self.assertIn('0.900%',p.estimate.get());self.assertEqual(self.venue.posts,[])
        self.app.blocked.set(False);self.app.toggle_block();self.assertEqual(self.venue.posts,[])
        self.app.place(p);self.pump(lambda:not self.app.busy)
        self.assertEqual(len(self.venue.posts),1);self.assertEqual(self.app.engine.public()['fills'],0)
    def test_cancel_and_refresh_ticket_is_a_draft_and_requires_new_click(self):
        self.connect();p=self.app.panel();p.use_price('ASK');p.size.set('.001')
        self.app.blocked.set(False);self.app.toggle_block();self.app.place(p);self.pump(lambda:not self.app.busy)
        order=next(iter(self.app.engine.state()['orders'].values()));tree=self.app.trees['Open orders'];tree.selection_set('owned_'+order['cid'])
        self.venue.fill(order['order_id'],'.0004');self.app.cancel_selected(True);self.pump(lambda:not self.app.busy)
        self.assertEqual(p.size.get(),'0.0006');self.assertEqual(p.replaces,order['cid']);self.assertEqual(len(self.venue.posts),1)
    def test_stale_market_clears_book_and_disables_ticket(self):
        self.connect();self.clock.tick(31);self.app.connected=False
        self.pump(lambda:not self.app.panel().book_tree.get_children())
        self.assertEqual(self.app.panel().book_tree.get_children(),());self.assertIn('disabled',self.app.panel().trade_button.state())
    def test_resize_keeps_book_and_complete_ticket_inside_window(self):
        for width,height in ((1450,920),(1040,780)):
            self.resize(width,height);p=self.app.panel()
            self.assertEqual((self.root.winfo_width(),self.root.winfo_height()),(width,height))
            for widget in (p.book_tree,p.trade_button,p.size_entry,p.price_entry,self.app.balance_tree):
                with self.subTest(size=(width,height),widget=str(widget)):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreater(widget.winfo_width(),20)
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+width)
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.root.winfo_rooty()+height)
    def test_resize_waits_for_deferred_native_configure_before_measuring_children(self):
        self.resize(1450,920);native=self.root.geometry
        def deferred(spec):self.root.after(50,lambda:native(spec))
        with patch.object(self.root,'geometry',side_effect=deferred):self.resize(1040,780)
        self.assertEqual((self.root.winfo_width(),self.root.winfo_height()),(1040,780))
        p=self.app.panel()
        for w in (p.book_tree,p.trade_button,p.size_entry,p.price_entry,self.app.balance_tree):
            self.assertTrue(w.winfo_ismapped())
            self.assertLessEqual(w.winfo_rootx()+w.winfo_width(),self.root.winfo_rootx()+1040)
            self.assertLessEqual(w.winfo_rooty()+w.winfo_height(),self.root.winfo_rooty()+780)
    def test_manual_monitor_and_eight_section_diagnostics_are_quantity_and_identity_free(self):
        self.connect();snapshot=capture(self.app,session='0'*32,sequence=1,now=self.clock.wall())
        self.assertEqual(snapshot['manual_execution']['provider'],'COINBASE_MANUAL_LIMIT_GTC')
        self.assertFalse(snapshot['manual_execution']['automation']);raw=encode(snapshot).decode();report=diagnostic(self.app)
        self.assertEqual(sum('['+str(i)+'/8]' in report for i in range(1,9)),8)
        for secret in (self.tmp.name,'0.030010',cid(500),cid(1000)):
            self.assertNotIn(secret,raw);self.assertNotIn(secret,report)
        changed=deepcopy(snapshot);changed['manual_execution']['price']='0.03'
        with self.assertRaises(ValueError):encode(changed)
    def test_close_during_unknown_cancel_is_bounded_and_preserves_lock(self):
        self.connect();p=self.app.panel();p.use_price('ASK');p.size.set('.001');self.app.blocked.set(False);self.app.toggle_block()
        self.app.place(p);self.pump(lambda:not self.app.busy)
        self.venue.cancel_orders=lambda **kwargs:(_ for _ in ()).throw(TimeoutError())
        self.app.close();self.pump(lambda:self.app.closed)
        self.assertTrue(self.app.engine.block.is_set());self.assertEqual(self.app.engine.public()['unresolved'],1)
        self.assertEqual(len(self.venue.posts),1)
    def test_stop_during_slow_preview_prevents_order_before_post(self):
        self.connect();entered=threading.Event();release=threading.Event();original=self.venue.preview_limit_order_gtc_sell
        def delayed(**kwargs):entered.set();release.wait(3);return original(**kwargs)
        self.venue.preview_limit_order_gtc_sell=delayed;p=self.app.panel();p.use_price('ASK');p.size.set('.001')
        self.app.blocked.set(False);self.app.toggle_block();self.app.place(p);self.assertTrue(entered.wait(1))
        self.app.blocked.set(True);self.app.toggle_block();release.set();self.pump(lambda:not self.app.busy)
        self.assertEqual(self.venue.posts,[]);self.assertTrue(self.app.engine.block.is_set())
