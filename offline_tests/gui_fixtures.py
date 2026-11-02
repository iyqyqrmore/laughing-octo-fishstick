"""Synthetic account/quote fixtures and deterministic Tk lifetime for v100 tests."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3,unittest

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


class SimpleGUI(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict('os.environ',{'COINCAT_DATA_DIR':self.temp.name});self.env.start();self.addCleanup(self.env.stop)
        from coincat_app import CoinCatApp
        self.root=tk.Tk();self.app=CoinCatApp(self.root)
        background_errors=[]
        self.root.report_callback_exception=lambda cls,value,trace:background_errors.append(f'{cls.__name__}: {value}')
        self.root.tk.createcommand('bgerror',lambda message:background_errors.append(str(message)))
        def close_gui():
            try:
                if not self.app.closed:self.root.update_idletasks()
            finally:
                self.app._close()
            # Tcl's event queue survives destruction of the Tk window. Drain
            # idle theme events while this interpreter and error collector live.
            self.root.tk.call('update','idletasks')
            self.assertFalse(background_errors,'Tk background errors: '+repr(background_errors))
        self.addCleanup(close_gui)
        self.root.update_idletasks()
