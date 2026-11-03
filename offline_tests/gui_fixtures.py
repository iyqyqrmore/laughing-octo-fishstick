"""Synthetic account/quote fixtures and deterministic Tk lifetime for v1.02 tests."""
from contextlib import closing,contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3,time,unittest

from coincat_live import LiveLedger
from coincat_live_forward_store import ForwardStore
from coincat_v502_fee_learning import FeeLearning
from coincat_v701_transport import QuoteSnapshot
from coincat_scanner import Scanner
from offline_tests.test_native_receipts import market,NOW


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
    with closing(sqlite3.connect(ledger.path)) as db:return '\n'.join(db.iterdump())


@contextmanager
def gui_lifetime():
    """Guard every test interpreter, including windows created to test restart."""
    import tkinter as tk
    from coincat_app import CoinCatApp
    root=tk.Tk();background_errors=[];app=None
    root.report_callback_exception=lambda cls,value,trace:background_errors.append(f'{cls.__name__}: {value}')
    root.tk.createcommand('bgerror',lambda message:background_errors.append(str(message)))
    try:
        app=CoinCatApp(root)
        root.update_idletasks()
        yield root,app
    finally:
        try:
            # ThemeChanged needs a live Tk event command. Finish pending native
            # idle work before destruction, without running app timers/workers.
            if app is None or not app.closed:root.update_idletasks()
        finally:
            if app is None:root.destroy()
            else:
                app._close()
                deadline=time.monotonic()+5
                while not app.shutdown_complete.is_set() and time.monotonic()<deadline:
                    root.tk.call('update');time.sleep(.005)
                if not app.shutdown_complete.is_set():raise AssertionError('GUI worker did not finish clean shutdown')
            # Keep the collector alive while any post-destruction idle errors
            # surface; these must fail the test rather than only print to Tcl.
            root.tk.call('update','idletasks')
            if background_errors:raise AssertionError('Tk background errors: '+repr(background_errors))


class SimpleGUI(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict('os.environ',{'COINCAT_DATA_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
        self.root,self.app=self.enterContext(gui_lifetime())
        if getattr(self,'legacy_workspace',True):
            self.app.tabs.select(self.app.tabs.tabs()[-1]);self.app.archive_tabs.select(self.app.research_page)
            self.root.update_idletasks()
