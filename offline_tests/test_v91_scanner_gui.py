"""Read-only scanner, real Tk controls, stop behavior and current diagnostics."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import sqlite3,threading,time,unittest

from coincat_live import LiveLedger
from coincat_live_forward_store import ForwardStore
from coincat_v502_fee_learning import FeeLearning
from coincat_v701_transport import QuoteSnapshot
from coincat_scanner import Scanner
from offline_tests.test_v91_full_balance import market,NOW


class FakeClient:
    def __init__(self):self.q,self.rules=market();self.calls=[]
    def get_api_key_permissions(self):
        self.calls.append('permissions');return {'can_view':True,'can_trade':True,'can_transfer':False}
    def get_accounts(self,**kwargs):
        self.calls.append('accounts');return {'accounts':[{'currency':'BTC','available_balance':{'value':'.002'},'hold':{'value':'0'}}],'has_next':False}
    def get_products(self,**kwargs):
        self.calls.append('products');return {'products':list(self.rules.values())}
    def get_transaction_summary(self,**kwargs):
        self.calls.append('fees');return {'fee_tier':{'maker_fee_rate':'.005','taker_fee_rate':'.009'}}
    def create_order(self,*args,**kwargs):raise AssertionError('NO_REAL_ORDER')
    def preview_order(self,*args,**kwargs):raise AssertionError('NO_AUTHENTICATED_PREVIEW')


def setup(folder):
    root=Path(folder);ledger=LiveLedger(root/'CoinCat_Live_Orders.sqlite3')
    ledger.approve_all({'BTC':'.001'})  # Full AVAILABLE is explicitly requested, not this older quantity.
    client=FakeClient()
    s=Scanner(ledger,client,FeeLearning(root/'research_data'/'fees.sqlite3'),ForwardStore(root/'research_data'/'quotes.sqlite3'))
    return ledger,client,s


def collector(client,at=NOW):
    def collect(pairs,**kwargs):
        return {p:QuoteSnapshot(p,client.q[p][0],client.q[p][1],at,at,1) for p in pairs}, {}, 1
    return collect


def ledger_dump(ledger):
    with sqlite3.connect(ledger.path) as db:return '\n'.join(db.iterdump())


class ReadOnlyScanner(unittest.TestCase):
    def test_complete_fake_account_to_full_balance_policy_without_private_writes(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=setup(folder);before=ledger_dump(ledger)
            s.refresh(now=NOW)
            result=s.scan(now=NOW,collect=collector(client))
            self.assertIsNotNone(result['best'])
            self.assertEqual(result['best']['available'],s.balances['BTC'])
            self.assertEqual(str(result['best']['available']),'0.002')
            self.assertEqual(before,ledger_dump(ledger))
            self.assertEqual(set(client.calls),{'permissions','accounts','products','fees'})
            self.assertEqual(result['orders_submitted'],0)
            self.assertFalse(result['live_order_permission'])
            self.assertGreater(result['quotes_recorded'],0)

    def test_stop_before_or_during_quotes_does_not_publish_or_learn(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=setup(folder);s.refresh(now=NOW)
            cancelled=threading.Event();cancelled.set();collect=Mock()
            self.assertEqual(s.scan(now=NOW,cancel=cancelled,collect=collect)['state'],'CANCELLED')
            collect.assert_not_called();cancelled.clear()
            def stop_during(pairs,**kwargs):
                cancelled.set();return collector(client)(pairs,**kwargs)
            self.assertEqual(s.scan(now=NOW,cancel=cancelled,collect=stop_during)['state'],'CANCELLED')
            self.assertEqual(s.sequence,0);self.assertEqual(s.lab.counts,{})
            self.assertIsNone(s.last_result)

    def test_excluded_holdings_are_not_reenabled_or_reapproved(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=setup(folder);ledger.set_asset_enabled('BTC',False)
            before=ledger_dump(ledger);s.refresh(now=NOW)
            result=s.scan(now=NOW,collect=collector(client))
            self.assertEqual(result['eligible_directions'],0)
            self.assertEqual(before,ledger_dump(ledger))

    def test_live_clock_uses_quote_receipt_time_not_pre_request_time(self):
        with TemporaryDirectory() as folder:
            ledger,client,s=setup(folder);s.refresh(now=NOW)
            qtime=[NOW]
            def delayed(pairs,**kwargs):
                qtime[0]=NOW+1
                return collector(client,at=NOW+1)(pairs,**kwargs)
            with patch('coincat_scanner.time.time',side_effect=lambda:qtime[0]):
                result=s.scan(collect=delayed)
            self.assertGreater(result['priced_directions'],0)
            self.assertEqual(result['at'],NOW+1)


class SimpleGUI(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict('os.environ',{'COINCAT_DATA_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
        from coincat_app import CoinCatApp
        self.root=tk.Tk();self.app=CoinCatApp(self.root);self.addCleanup(self.app._close)

    def test_five_actions_and_research_mixer_without_shadow_budgets_or_training(self):
        buttons=[];entries=[];labels=[]
        def visit(w):
            if w.winfo_class()=='TButton':buttons.append(w.cget('text'))
            if 'Entry' in w.winfo_class():entries.append(w)
            if w.winfo_class()=='TLabel':labels.append(w.cget('text'))
            for child in w.winfo_children():visit(child)
        visit(self.root)
        self.assertEqual(buttons[:5],['Import key JSON','Connect / refresh','Start scanning','STOP','Export diagnostics'])
        self.assertEqual(buttons[5:],['Reset']*6)
        self.assertEqual(len(entries),6)
        self.assertFalse(hasattr(self.app,'shadow_pilot'))
        self.assertFalse(hasattr(self.app,'experimental_shadow'))
        self.assertFalse(self.app.running)
        self.assertIn('LIVE blocked',self.root.title())
        self.assertIn('REAL SWAPS UNAVAILABLE',self.app.execution_text.get())

    def test_start_scan_stop_retains_findings_and_exports_eight_current_sections(self):
        app=self.app;client=FakeClient();app.scanner=Scanner(app.ledger,client,app.fees,app.market)
        app.scanner.refresh(now=NOW);app.connected=True
        with patch('coincat_scanner.time.time',return_value=NOW),patch('coincat_scanner.SCOUT.collect',side_effect=collector(client)):
            app._start();deadline=time.monotonic()+5
            while app.last_result is None and time.monotonic()<deadline:
                self.root.update();time.sleep(.005)
        self.assertIsNotNone(app.last_result)
        self.assertIn('BTC -> ETH',app.best_text.get())
        self.assertIn('Passive AI Lab',app.lab_text.get('1.0','end'))
        retained=deepcopy(app.last_result);app._stop()
        self.assertEqual(app.last_result,retained)
        path=Path(self.temp.name)/'diagnostics.txt'
        with patch('coincat_app.filedialog.asksaveasfilename',return_value=str(path)):app._export()
        text=path.read_text(encoding='utf-8')
        self.assertIn('SECTION COMPLETENESS: COMPLETE (8/8)',text)
        self.assertIn('PASSIVE AI LAB',text)
        self.assertIn('REAL SWAPS',app.execution_text.get())
        self.assertNotIn('SHADOW',text)
        self.assertNotIn(str(app.ledger.path),text)
        self.assertIn('sized_depth_impact',text)
        self.assertIn('UNKNOWN',text)

    def test_stop_discards_already_queued_scan_without_changing_display(self):
        app=self.app;app.running=True;generation=app.generation
        app.jobs.put(('scan',generation,{'best':'SHOULD_NOT_APPLY'},None))
        app._stop();app._poll()
        self.assertIsNone(app.last_result)
        self.assertFalse(app.running)
