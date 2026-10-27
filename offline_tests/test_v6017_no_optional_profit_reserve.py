"""v60.17: no discretionary 10% BUY withholding in research/experimental sizing.

All prices/product rules are artificial. Never touches Coinbase, financial
ledgers, LIVE orders, or user credentials.
"""
from __future__ import annotations
import unittest
from decimal import Decimal
from pathlib import Path
from coincat_multicurrency import evaluate_rotation

NOW=17_700_010
BOOKS={'SOL-USDC':('1','1.0005',NOW),
       'SOL-USD':('1','1.0005',NOW),
       'USDC-USD':('1','1.0002',NOW)}
CATALOG=set(BOOKS)
RULE={'base_increment':'0.01','base_min_size':'0.01','quote_min_size':'4.7'}


def idea(*, available='5', enrolled='5', cap='5', rules=None, fee='.009', slip='15', excluded=()):
    return evaluate_rotation(source='USDC',target='SOL', authorized_qty=enrolled,
        verified_available_qty=available,balance_age_s=1,
        catalog=CATALOG,quotes=BOOKS,now=NOW,usd_per_order_cap=cap,
        product_rules={'SOL-USDC':rules if rules is not None else RULE},
        fee_rate=fee,slippage_bps=slip,max_legs=1,excluded_assets=excluded)


class FullFuelReserveTests(unittest.TestCase):
    def test_small_holding_meets_product_min_only_without_legacy_10pct_holdback(self):
        # A $5 budget with 10% withholding could spend ~$4.5 and miss $4.7
        # minimum. Fee/slippage are still counted exactly in the spent input.
        plan=idea()
        self.assertEqual(plan['state'],'RESEARCH ONLY')
        step=plan['routes'][0]['steps'][0]
        self.assertEqual(step['pair'],'SOL-USDC')
        self.assertEqual(step['side'],'BUY')
        self.assertEqual(step['fee_rate_used'],Decimal('.009'))
        self.assertGreaterEqual(step['gross_base_quantity']*Decimal('1.0005')*Decimal('1.0015'),Decimal('4.7'))
        self.assertGreater(step['input_quantity'],Decimal('4.5'))
        self.assertLessEqual(step['input_quantity'],Decimal('5'))
        self.assertEqual(step['input_quantity'],step['gross_base_quantity']*Decimal('1.0005')*Decimal('1.0015')*Decimal('1.009'))
        self.assertEqual(len(plan['routes'][0]['steps']),1)
        self.assertLess(plan['routes'][0]['immediate_change_usd'],0)

    def test_true_minimum_still_blocks_underfunded_order(self):
        plan=idea(rules=dict(RULE,quote_min_size='5.1'))
        self.assertEqual(plan['state'],'WAIT')
        self.assertFalse(plan['routes'])
        self.assertTrue(any('minimum' in s for s in plan['route_rejections']))

    def test_verified_available_and_order_cap_are_never_overdrawn(self):
        # Approving $500 never makes unavailable or excluded balances spendable.
        p=idea(available='3.50',enrolled='500',cap='500',rules=dict(RULE,quote_min_size='1'))
        self.assertEqual(p['state'],'RESEARCH ONLY')
        self.assertLessEqual(p['routes'][0]['steps'][0]['input_quantity'],Decimal('3.50'))
        cap=idea(enrolled='10',available='10',cap='3.50',rules=dict(RULE,quote_min_size='1'))
        self.assertLessEqual(cap['routes'][0]['steps'][0]['approx_usd_notional'],Decimal('3.50'))
        nofund=idea(enrolled='3',available='3',cap='100',rules=dict(RULE,quote_min_size='4.7'))
        self.assertEqual(nofund['state'],'WAIT')
        banned=idea(excluded=('USDC',))
        self.assertEqual(banned['state'],'BLOCKED')

    def test_authentication_staleness_and_fee_checks_retained(self):
        missing=evaluate_rotation(source='USDC',target='SOL',authorized_qty='5',verified_available_qty='5',
            balance_age_s=1,catalog=CATALOG,quotes=BOOKS,now=NOW,usd_per_order_cap='5',
            product_rules={'SOL-USDC':RULE},fee_rate=None,max_legs=1)
        self.assertEqual(missing['state'],'WAIT')
        stale=evaluate_rotation(source='USDC',target='SOL',authorized_qty='5',verified_available_qty='5',
            balance_age_s=301,catalog=CATALOG,quotes=BOOKS,now=NOW,usd_per_order_cap='5',
            product_rules={'SOL-USDC':RULE},fee_rate='.009',max_legs=1)
        self.assertEqual(stale['state'],'WAIT')
        # A positive research mark must never be claimed just from spare funding.
        self.assertNotIn('order_authorized',idea())

    def test_gui_reserve_notice_no_longer_suggests_protected_profits(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/'app/coincat_app.py').read_text(encoding='utf-8')
        researcher=(root/'app/coincat_multicurrency.py').read_text(encoding='utf-8')
        self.assertIn('No automatic profit reserve or extra 10% BUY holdback',app)
        self.assertNotIn('available/BUFFER',researcher)
        self.assertNotIn('BUY reserves 10% of input-asset liquidity',researcher)
        self.assertIn('No extra 10% holding reserve',researcher)
        self.assertIn('Per-order USD cap or funding balance exceeded',researcher)

if __name__=='__main__':unittest.main()
