"""v60.7.1: explicit full portfolio SHADOW mode and read-only SELL-origin auditing.
Entire suite uses fake quotes and synthetic wallet amounts. No Coinbase calls.
"""
import unittest,tempfile,json
from pathlib import Path
from decimal import Decimal
from coincat_v606_budgets import DEFAULT,load,save,validate,effective
from coincat_rotation_autopilot import auto_rotation_screen
from coincat_v605_shadow_bridge import shadow_screen
from coincat_version import DISPLAY

TS=1800000000
CAT=['ETH-USD','BTC-USD','USDC-USD']
BOOKS={'ETH-USD':('2000','2000.4',TS),'BTC-USD':('50000','50001',TS),'USDC-USD':('0.99999','1.0',TS)}
RULE={'base_increment':'0.00000001','base_min_size':'0.00000001','quote_min_size':'0.01'}
FEES={pair:Decimal('.009') for pair in CAT}

class FullFuelShadow(unittest.TestCase):
    def test_backward_compatible_old_manual_pref_and_persisted_full_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'shadow_budget.json'
            old={key:value for key,value in DEFAULT.items() if key!='mode'}
            file.write_text(json.dumps(old))
            self.assertEqual(load(file)['mode'],'MANUAL')
            old.update(mode='FULL_AVAILABLE')
            saved=save(file,old)
            self.assertEqual(load(file),saved)
            self.assertEqual(effective(saved,'72.45')['per_order_usd'],'72.45')
            self.assertEqual(effective(saved,'72.45')['daily_buy_usd'],saved['daily_buy_usd'])
            self.assertEqual(effective(saved,'72.45')['incremental_exposure_usd'],'72.45')
            self.assertEqual(effective(saved,'72.45')['max_attempts'],'12')
            self.assertEqual(effective(saved,'95.5')['per_order_usd'],'95.5')
            self.assertEqual(effective(saved,'0.5')['per_order_usd'],'0.5')
            self.assertIsNone(effective(saved,'0'))
            self.assertIsNone(effective(saved,'NaN'))
            self.assertEqual(load(file)['attempts_24h'],'12')
    def test_manual_dollars_not_silently_changed(self):
        manual=dict(DEFAULT,mode='MANUAL',per_order_usd='5',daily_buy_usd='15',added_exposure_usd='25')
        expected=effective(manual,'100')
        self.assertEqual(expected['per_order_usd'],'5')
        self.assertEqual(expected['daily_buy_usd'],'15')
        self.assertEqual(expected['incremental_exposure_usd'],'25')
        self.assertEqual(expected['mode'],'MANUAL')
        with self.assertRaises(ValueError):validate(dict(DEFAULT,mode='UNLIMITED'))
    def test_all_funding_exit_screen_independent_of_buy_signal(self):
        inventory=[{'asset':'ETH','remaining_qty':'1','enabled':1},
                   {'asset':'USDC','remaining_qty':'100','enabled':1},
                   {'asset':'UNVERIFIED','remaining_qty':'100','enabled':1}]
        out=auto_rotation_screen(buy_signals=[],holdings=inventory,
            verified_balances={'ETH':'1','USDC':'100','UNVERIFIED':'100'},balance_age_s=10,
            catalog=CAT,quotes=BOOKS,product_rules={k:RULE for k in CAT},
            usd_per_order_cap='2000',now=TS,fee_rates_by_pair=FEES)
        self.assertEqual(out['state'],'WAIT')
        self.assertEqual(out['considered'],0)
        self.assertEqual(out['sell_first']['screened'],1)
        self.assertEqual(out['sell_first']['feasible_exit_routes'],1)
        self.assertEqual(out['sell_first']['cost_drag_exits'],1)
        self.assertFalse(out['sell_first']['order_authorized'])
        self.assertEqual(out['sell_first']['positive_future_usd_edge_verified'],0)
        self.assertFalse(out['ideas'])
    def test_newly_acquired_shadow_inventory_valued_and_rechecked(self):
        kwargs=dict(excluded=['ETH'],buy_signals=[],age_s=10,catalog=CAT,
            quotes=BOOKS,product_rules={k:RULE for k in CAT},portfolio_usd_cap=Decimal('1e24'),
            now=TS,fee_rates_by_pair=FEES,relative_evidence=None)
        old=shadow_screen(balances={'USD':'1500'},**kwargs)
        new=shadow_screen(balances={'BTC':'0.03','USD':'5'},**kwargs)
        self.assertEqual(old['sell_first']['screened'],0)
        self.assertEqual(new['sell_first']['screened'],1)
        self.assertEqual(new['sell_first']['feasible_exit_routes'],1)
        self.assertEqual(new['state'],'WAIT')
        self.assertEqual(new['route_attempts'],0)
        self.assertEqual(new['sell_first']['positive_future_usd_edge_verified'],0)
    def test_source_display_and_live_post_stays_unconditionally_blocked(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        s=(root/'app/coincat_app.py').read_text()
        self.assertIn('Use Full Available Enrolled Portfolio (SHADOW only)',s)
        self.assertIn('mode=self.shadow_budget_mode.get()',s)
        self.assertEqual(s.count('auto_rotation_screen('),1)
        self.assertIn('SELL-first spot exits studied=',s)
        self.assertEqual(DISPLAY,'CoinCat v80.0')
        broker=(root/'app/coincat_live.py').read_text()
        self.assertIn('def submit(',broker)
        import ast
        tree=ast.parse(broker)
        obj=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        submit=next(n for n in obj.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        self.assertIsInstance(submit.body[0],ast.Raise)

if __name__=='__main__':unittest.main()
