"""Real Tk controls with fake venue events; offline, no private installation."""
from copy import deepcopy
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
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
    def pump(self,predicate,seconds=None):
        # Native Windows storage/painting can exceed the Linux fixture budget.
        if seconds is None:seconds=30 if sys.platform=='win32' else 5
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:self.root.update();time.sleep(.005)
        self.assertTrue(predicate(),'bounded worker did not finish; busy='+str(self.app.busy)+
            ', closing='+str(self.app.closing)+', worker_alive='+str(bool(self.app.worker and self.app.worker.is_alive()))+
            ', callback_errors='+repr(self.errors));self.root.update_idletasks()
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
    def test_default_entry_has_seven_tabs_one_hour_charts_and_no_redundant_market_controls(self):
        self.assertEqual(len(self.app.tabs.tabs()),7);self.assertEqual(self.app.market.get(),'ETH-BTC')
        self.assertTrue(self.app.blocked.get());self.assertFalse(hasattr(self.app,'live_coordinator'));self.assertFalse(hasattr(self.app,'paper'))
        self.assertFalse(hasattr(self.app,'market_box'));self.assertFalse(hasattr(self.app,'star'))
        self.assertFalse(hasattr(self.app,'toggle_favorite'))
        self.assertEqual({panel.interval.get() for panel in self.app.panels.values()},{'1h'})
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_portfolio_worker_refreshes_unwatched_holdings_without_funding_or_order_changes(self):
        from offline_tests.test_portfolio_display import breakdown
        raw=breakdown();self.venue.get_portfolio_breakdown=lambda **kwargs:deepcopy(raw)
        favorite_path=Path(self.tmp.name)/'research_data'/'spot_manual'/'favorites.json';favorite_path.write_text('[]',encoding='utf-8')
        self.connect();self.pump(lambda:self.app.portfolio_snapshot is not None and not self.app.busy)
        self.assertEqual(self.app.panel().chart_data['interval'],'1h')
        self.assertIn('$123.45',self.app.portfolio_badge.amount.cget('text'))
        self.assertIn('VTHO',self.app.portfolio_badge.hover_text);self.assertIn('VET',self.app.portfolio_badge.hover_text)
        account=deepcopy(self.app.account);limits=deepcopy(self.app.engine.state()['limits'])
        raw['breakdown']['portfolio_balances']['total_balance']['value']='133.45'
        raw['breakdown']['spot_positions'][0]['total_balance_fiat']=110.
        self.app.portfolio_reader.next_due=time.monotonic()-30;self.app.refresh_due=self.clock.wall()-1
        with patch.object(self.app,'work',wraps=self.app.work) as work:
            self.pump(lambda:'$133.45' in self.app.portfolio_badge.amount.cget('text') and not self.app.busy)
        self.assertEqual(work.call_args_list[0].args[0],'portfolio')
        self.assertEqual(self.app.account['available'],account['available']);self.assertEqual(self.app.engine.state()['limits'],limits)
        self.assertFalse(hasattr(self.app,'shadow'));self.assertIsNone(self.app.intelligent.state());self.assertTrue(self.app.blocked.get())
        self.assertEqual(favorite_path.read_text(encoding='utf-8'),'[]')
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_holdings_hover_updates_live_and_long_lists_stay_bounded(self):
        from offline_tests.test_portfolio_display import breakdown
        from coincat_portfolio_display import parse_portfolio
        raw=breakdown();badge=self.app.portfolio_badge;self.app.connected=True;self.app.refresh_due=self.clock.wall()+10000
        self.app.portfolio_reader.next_due=time.monotonic()+10000
        self.app.portfolio_snapshot=dict(data=parse_portfolio(raw,raw['breakdown']['portfolio']['uuid'],self.clock.wall()),failed=False)
        badge.render(self.app.portfolio_snapshot,self.clock.wall(),True);hover=badge.amount.hover_help
        hover.anchor=(badge.amount.winfo_rootx()+8,badge.amount.winfo_rooty()+8);hover.show();self.root.update_idletasks()
        self.assertIn('$123.45',hover.shown_text)
        scope=self.app.portfolio_snapshot['data']['portfolio']
        for i in range(80):raw['breakdown']['spot_positions'].append(dict(asset='COIN'+str(i),account_uuid=cid(50000+i),total_balance_crypto=1,total_balance_fiat=1))
        raw['breakdown']['portfolio_balances']['total_balance']['value']='203.45'
        self.app.portfolio_snapshot=dict(data=parse_portfolio(raw,scope,self.clock.wall()),failed=False)
        badge.render(self.app.portfolio_snapshot,self.clock.wall(),True);self.root.update_idletasks()
        self.assertIn('$203.45',hover.shown_text);self.assertIsNotNone(hover.body)
        self.assertLessEqual(hover.window.winfo_height(),480)
        hover.hide();self.assertIsNone(hover.window)
    def test_portfolio_staleness_is_visible_and_private_values_never_enter_exports(self):
        from offline_tests.test_portfolio_display import breakdown
        self.venue.get_portfolio_breakdown=lambda **kwargs:breakdown();self.connect()
        self.pump(lambda:self.app.portfolio_snapshot is not None and not self.app.busy)
        snapshot=capture(self.app,session='0'*32,sequence=1,now=self.clock.wall());raw=encode(snapshot).decode();report=diagnostic(self.app)
        for secret in ('$123.45','123.45','VTHO','VET',cid(40000)):
            self.assertNotIn(secret,raw);self.assertNotIn(secret,report)
        self.clock.tick(31);self.app.connected=False
        self.pump(lambda:'Stale' in self.app.portfolio_badge.caption.cget('text'))
        self.assertIn('$123.45',self.app.portfolio_badge.amount.cget('text'))
    def test_header_total_and_transparent_logo_are_inset_at_both_window_sizes(self):
        original=None
        for width,height in ((1450,920),(1040,780)):
            self.resize(width,height);badge=self.app.portfolio_badge;logo=self.app.logo_label
            relative=logo.winfo_rootx()-self.root.winfo_rootx()
            if original is None:original=relative
            else:self.assertEqual(relative,original)
            self.assertGreater(badge.winfo_rootx(),self.app.badge.winfo_rootx()+self.app.badge.winfo_width())
            self.assertGreaterEqual(logo.winfo_rootx(),badge.winfo_rootx()+badge.winfo_width())
            self.assertLess(logo.winfo_rootx()+logo.winfo_width(),self.root.winfo_rootx()+width-20)
            self.assertLessEqual(badge.winfo_rooty()+badge.winfo_height(),self.app.shadow_summary_label.winfo_rooty())
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
    def test_imported_filled_trade_and_csv_corroboration_reach_exports_without_execution_credit(self):
        from offline_tests.test_beta_evidence import native_record
        from offline_tests.test_spot_manual import iso,NOW,OID
        order,fills=native_record(currency=None)
        self.venue.orders[OID]=order;self.venue.fills[OID]=fills
        self.connect();self.clock.tick(110)
        self.app.import_history(OID);self.pump(lambda:not self.app.busy)
        def exported():return capture(self.app,session='0'*32,sequence=1,now=self.clock.wall())
        before=exported();history=before['beta']['manual'];own=before['manual_execution']
        self.assertEqual((history['state'],history['orders'],history['filled'],history['known_native_flow'],history['unknown']),
            ('OBSERVED',1,1,0,1))
        self.assertEqual((own['orders'],own['fills'],own['unresolved']),(0,0,0))
        self.assertFalse(history['execution_authority'])
        report=diagnostic(self.app)
        self.assertIn('Imported Coinbase history: OBSERVED; orders 1; filled 1',report)
        self.assertIn('order attempts 0; CoinCat fills 0',report)
        # Re-reading an identical order must not inflate imported counts.
        self.app.import_history(OID);self.pump(lambda:not self.app.busy)
        self.assertEqual(exported()['beta']['manual']['orders'],1)
        path=Path(self.tmp.name)/'statement.csv'
        with path.open('w',newline='',encoding='utf-8') as file:
            writer=csv.DictWriter(file,fieldnames=['ID','Timestamp','Transaction Type','Asset','Quantity Transacted','Notes'])
            writer.writeheader();writer.writerow(dict(ID='synthetic_statement',Timestamp=iso(NOW+106),
                **{'Transaction Type':'Advanced Trade Sell','Asset':'ETH','Quantity Transacted':'-.005',
                   'Notes':'Sold 0.005 ETH for 0.0001505833 BTC on ETH-BTC at 0.030268 BTC/ETH'}))
        with patch('coincat_spot_app.filedialog.askopenfilename',return_value=str(path)):self.app.import_statement()
        self.pump(lambda:not self.app.busy);after=exported();history=after['beta']['manual']
        self.assertEqual((history['orders'],history['filled'],history['known_native_flow'],history['unknown']),(1,1,1,0))
        self.assertEqual((after['manual_execution']['orders'],after['manual_execution']['fills']),(0,0))
        self.assertEqual(self.app.history_store.records()[0]['fills'],fills)
        self.assertEqual(self.app.history_store.records()[0]['report']['fee_currencies'],[None])
        self.assertEqual((self.venue.posts,self.venue.cancels),([],[]))
        for text in (encode(after).decode(),diagnostic(self.app)):
            for private in (OID,self.tmp.name,'0.030268','0.0001505833'):
                self.assertNotIn(private,text)
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
