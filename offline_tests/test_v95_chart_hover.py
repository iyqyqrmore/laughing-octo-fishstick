"""History correctness, pointer-bounded help and available-ETH defaults."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import threading
import time
import unittest
from unittest.mock import patch

from coincat_chart import read_history,range_start
from coincat_hover import popup_geometry,visible_bounds
from coincat_live_forward_store import ForwardStore
from coincat_working_allocation import AllocationRow
from offline_tests import gui_fixtures as fixtures
from offline_tests.test_v95_eth_growth import prepare,run_growth
from offline_tests.test_native_receipts import NOW

BASE=1700000040  # Past UTC minute boundary, synthetic prices only.


class QuoteHistory(unittest.TestCase):
    def store(self,folder):
        path=Path(folder)/'quotes.sqlite3';store=ForwardStore(path)
        store.record_quotes([('ADA-ETH',BASE, '1','1','TEST'),
            ('ADA-ETH',BASE+10,'3','3','TEST'),('ADA-ETH',BASE+20,'2','2','TEST'),
            ('ADA-ETH',BASE+180,'4','4','TEST'),('ETH-BTC',BASE,'2','4','TEST'),
            ('ADA-USD',BASE,'50','60','TEST')])
        return path

    def test_ohlc_samples_count_gaps_and_whole_stored_range_without_network_or_mutation(self):
        with TemporaryDirectory() as folder:
            path=self.store(folder);before=hashlib.sha256(path.read_bytes()).hexdigest()
            result=read_history(path,'ADA-ETH',interval='1m',span='All stored',end=BASE+240)
            self.assertEqual(result['state'],'QUOTE_CANDLES')
            self.assertEqual(len(result['candles']),2)  # No invented candles across the 2-minute gap.
            first=result['candles'][0]
            self.assertEqual((first['open'],first['high'],first['low'],first['close'],first['samples']),(1,3,1,2,3))
            self.assertEqual((result['oldest'],result['newest'],result['stored_samples']),(BASE,BASE+180,4))
            self.assertEqual(result['products'],['ADA-ETH','ETH-BTC'])
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertIn('NOT_TRADE_OHLC',result['basis'])

    def test_inverse_products_chart_in_eth_per_coin_and_missing_time_is_empty(self):
        with TemporaryDirectory() as folder:
            path=self.store(folder)
            result=read_history(path,'ETH-BTC',span='All stored',end=BASE+1)
            self.assertEqual(result['candles'][0]['close'],.375)  # mean(1/ask,1/bid)
            empty=read_history(path,'ADA-ETH',span='1 minute',end=BASE+3600)
            self.assertEqual(empty['state'],'NO_QUOTES_IN_RANGE')
            self.assertEqual(empty['candles'],[])
            missing=read_history(path,'SOL-ETH')
            self.assertEqual(missing['state'],'NO_STORED_QUOTES')

    def test_second_candles_are_only_recorded_samples_and_wide_views_fit_explicitly(self):
        with TemporaryDirectory() as folder:
            path=self.store(folder)
            seconds=read_history(path,'ADA-ETH',span='1 minute',interval='1s',end=BASE+30)
            self.assertEqual(len(seconds['candles']),3)
            self.assertTrue(all(r['samples']==1 for r in seconds['candles']))
            wide=read_history(path,'ADA-ETH',span='All stored',interval='1s',end=BASE+31536000)
            self.assertEqual(wide['requested_interval'],'1s');self.assertNotEqual(wide['interval'],'1s')
            self.assertLessEqual(len(wide['candles']),500)

    def test_calendar_month_and_year_boundaries_and_early_cancel(self):
        feb=datetime(2024,2,29,12,tzinfo=timezone.utc).timestamp()
        self.assertEqual(datetime.fromtimestamp(range_start(feb,'1 year'),timezone.utc).isoformat(),'2023-02-28T12:00:00+00:00')
        march=datetime(2024,3,31,12,tzinfo=timezone.utc).timestamp()
        self.assertEqual(datetime.fromtimestamp(range_start(march,'1 month'),timezone.utc).day,29)
        with TemporaryDirectory() as folder:
            path=self.store(folder);cancel=threading.Event();cancel.set()
            self.assertEqual(read_history(path,cancel=cancel)['state'],'CANCELLED')
            result=read_history(path,'ADA-ETH',span='All stored',interval='1 month',end=BASE+31536000)
            dt=datetime.fromtimestamp(result['candles'][0]['at'],timezone.utc)
            self.assertEqual((dt.day,dt.hour,dt.minute,dt.second),(1,0,0,0))

    def test_future_observations_do_not_become_historical_candles(self):
        with TemporaryDirectory() as folder:
            path=self.store(folder);store=ForwardStore(path)
            store.record_quotes([('ADA-ETH',time.time()+86400,'999','999','TEST')])
            result=read_history(path,'ADA-ETH',span='All stored')
            self.assertEqual(result['newest'],BASE+180)
            self.assertTrue(all(row['high']<=4 for row in result['candles']))


class PopupPlacement(unittest.TestCase):
    def test_every_edge_and_negative_monitor_coordinates_keep_popup_inside(self):
        for bounds in ((0,0,1000,740),(-1200,0,0,900),(50,80,800,500)):
            left,top,right,bottom=bounds
            for anchor in ((left+2,top+2),(right-2,bottom-2),(right-2,top+2),(left+2,bottom-2)):
                x,y,w,h=popup_geometry(anchor,bounds,520,480)
                self.assertGreaterEqual(x,left);self.assertGreaterEqual(y,top)
                self.assertLessEqual(x+w,right);self.assertLessEqual(y+h,bottom)
                if anchor[1]>bottom-50:self.assertLess(y,anchor[1])


class GrowthChartGUI(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def test_closing_waits_for_public_history_sqlite_handle_to_close(self):
        from contextlib import closing
        import sqlite3
        started=threading.Event();released=threading.Event()
        def held_reader(path,pair,**kwargs):
            with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
                db.execute('PRAGMA query_only=ON');started.set()
                if not kwargs['cancel'].wait(1):raise AssertionError('Reader cancellation missing')
            released.set();return {'state':'CANCELLED','candles':[]}
        chart=self.app.chart
        with patch('coincat_chart.read_history',side_effect=held_reader):
            chart.refresh();self.assertTrue(started.wait(1));self.app._close()
        self.assertTrue(released.is_set());self.assertFalse(chart.reader.is_alive())

    def connect(self):
        _,client,s=prepare(self.temp.name);self.app.scanner=s;self.app.connected=True
        self.app.allocation_editor.clock=lambda:NOW;self.app._render_wallet()
        return client,s

    def test_available_eth_is_default_exact_and_custom_amount_survives_refresh_and_reset(self):
        _,s=self.connect();fader=self.app.mixer.controls['amount_eth']
        self.assertEqual(fader.value,D(2));self.assertFalse(fader.customized)
        self.app.mixer.commit_entries();self.assertFalse(fader.customized)
        fader._entered();self.assertFalse(fader.customized)  # Focus-out alone isn't an edit.
        s.balances['ETH']=D('20.123456789012345678');self.app._render_wallet()
        self.assertEqual(fader.value,s.balances['ETH']);self.assertGreater(fader.maximum,D(10))
        fader.set(D('.125'));s.balances['ETH']=D(3);self.app._render_wallet()
        self.assertEqual(fader.value,D('.125'));fader.reset();self.assertEqual(fader.value,D(3))
        self.assertFalse(fader.customized)
        defaults=self.app.mixer.values()
        for key,value in dict(entry_offset_bps=D(0),target_pct=D('.25'),expiry_hours=D(24),
                              scan_interval_s=D(5),taker_slippage_bps=D(15)).items():self.assertEqual(defaults[key],value)

    def test_eth_default_respects_manual_protected_excluded_and_invalid_drafts(self):
        _,s=self.connect();editor=self.app.allocation_editor
        editor.tree.selection_set('ETH');editor._select()
        editor.fields['manual'].set('.5');editor.fields['protected'].set('.25');editor.apply_selected()
        fader=self.app.mixer.controls['amount_eth'];self.assertEqual(fader.value,D('1.25'))
        self.app.ledger.approve_all({'ETH':'2'});self.app.ledger.set_asset_enabled('ETH',False)
        self.app._render_wallet();self.assertEqual(fader.value,0)
        self.assertIsNone(self.app.applied_config)

    def test_long_readout_popup_uses_pointer_flips_up_fits_and_scrolls(self):
        client,s=self.connect();result=run_growth(s,client)
        self.app.last_result=result;self.app._render(result);self.root.update()
        tip=self.app.growth_tree.hover_help
        left,top=self.root.winfo_rootx()+10,self.root.winfo_rooty()+10
        bounds=(left,top,left+800,top+300);tip.anchor=(left+790,top+290)
        with patch('coincat_hover.visible_bounds',return_value=bounds):tip.show()
        self.root.update_idletasks();window=tip.window
        self.assertIsNotNone(tip.body)
        self.assertLess(window.winfo_rooty(),tip.anchor[1])
        self.assertGreaterEqual(window.winfo_rootx(),left);self.assertGreaterEqual(window.winfo_rooty(),top)
        self.assertLessEqual(window.winfo_rootx()+window.winfo_width(),bounds[2])
        self.assertLessEqual(window.winfo_rooty()+window.winfo_height(),bounds[3])
        tip.body.yview_moveto(1);self.root.update_idletasks();self.assertGreater(tip.body.yview()[0],0)
        tip.hide();self.assertIsNone(tip.window)

    def test_chart_above_research_async_history_and_stale_stop_result_rejected(self):
        client,s=self.connect();run_growth(s,client)
        chart=self.app.chart;chart.set_products(['ADA-ETH']);chart.span.set('All stored');chart.refresh()
        deadline=time.monotonic()+4
        while chart.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.005)
        # Fixture's NOW is in the future relative to this host; inject past public data for chart evidence.
        self.app.market.record_quotes([('ADA-ETH',BASE,'1','1','TEST'),('ADA-ETH',BASE+10,'2','2','TEST')])
        chart.refresh();deadline=time.monotonic()+4
        while (chart.busy or chart.pending) and time.monotonic()<deadline:
            self.root.update();time.sleep(.005)
        self.assertEqual(chart.result['state'],'QUOTE_CANDLES')
        self.assertGreater(len(chart.canvas.find_all()),5)
        self.root.geometry('1000x740');self.root.update()
        self.assertLess(chart.winfo_rooty(),self.app.growth_tree.winfo_rooty())
        self.assertLessEqual(self.app.growth_tree.winfo_rooty()+self.app.growth_tree.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        old=chart.result;generation=chart.generation;self.app._stop()
        chart.jobs.put((generation,dict(state='BAD_STALE_RESULT',candles=[])));chart.poll()
        self.assertIs(chart.result,old)
