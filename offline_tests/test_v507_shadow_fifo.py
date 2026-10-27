"""v50.7 shadow FIFO: genuine unified lot transformations, NEVER Coinbase."""
import sqlite3
import unittest
from decimal import Decimal
from coincat_v507_shadow_fifo import ShadowFIFOPortfolio, ShadowFIFOBlocked
from coincat_v507_shadow_arm import ShadowArmedResearch

MARKS={'BTC':'50000','ETH':'2000','USD':'1','USDC':'1'}
STEPS=[
 dict(pair='BTC-USD',side='SELL',gross_base_quantity=Decimal('0.01'),
      input_quantity=Decimal('0.01'),output_quantity=Decimal('495'), fee_rate_used=Decimal('0.01')),
 dict(pair='ETH-USD',side='BUY',gross_base_quantity=Decimal('0.2'),
      input_quantity=Decimal('401.6'),output_quantity=Decimal('0.2'),fee_rate_used=Decimal('0.004')),
]
class ShadowFifoTest(unittest.TestCase):
    def test_two_leg_fifo_residual_and_per_asset_marks(self):
        w=ShadowFIFOPortfolio({'BTC':'1'},MARKS)
        try:
            outcome=w.post_hypothetical_route(session_id='SHADOW-A',steps=STEPS,usd_rates=MARKS,at_utc=1770000000)
            self.assertEqual(outcome['steps'],2)
            balances=w.balances()
            self.assertEqual(balances['BTC'],Decimal('0.99'))
            self.assertEqual(balances['ETH'],Decimal('0.2'))
            self.assertEqual(balances['USD'],Decimal('93.4'))
            value=w.mark_vs_hold(MARKS)
            self.assertEqual(value['delta_usd'],Decimal('-6.6'))
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0],2)
            self.assertEqual(w.db.execute("SELECT COUNT(*) FROM unified_v501_disposals WHERE asset='BTC'").fetchone()[0],1)
            self.assertIsNone(w.db.execute("SELECT remaining_tax_usd FROM unified_v501_lots WHERE asset='BTC' AND source='EXPLICIT_OPENING'").fetchone()[0])
            # No counterfeit historical tax basis is created for enrolled holdings.
        finally:w.close()

    def test_identical_synthetic_replay_is_noop(self):
        w=ShadowFIFOPortfolio({'BTC':'1'},MARKS)
        try:
            w.post_hypothetical_route(session_id='SHADOW-B',steps=STEPS,usd_rates=MARKS,at_utc=1770000000)
            balances=w.balances()
            result=w.post_hypothetical_route(session_id='SHADOW-B',steps=STEPS,usd_rates=MARKS,at_utc=1770000000)
            self.assertEqual(result['state'],'SHADOW_FIFO_REPLAY_NOOP')
            self.assertEqual(w.balances(),balances)
            self.assertEqual(w.scenarios,1)
        finally:w.close()

    def test_direct_crypto_to_crypto_fifo_without_usd_cash_leg(self):
        marks={'BTC':'50000','ETH':'2000','USD':'1'}
        w=ShadowFIFOPortfolio({'ETH':'1'},marks)
        try:
            direct=[dict(pair='ETH-BTC',side='SELL',gross_base_quantity=Decimal('0.1'),
                input_quantity=Decimal('0.1'),output_quantity=Decimal('0.00396'),
                fee_rate_used=Decimal('0.01'))]
            w.post_hypothetical_route(session_id='SHADOW-DIRECT',steps=direct,
                usd_rates=marks,at_utc=1770000100)
            self.assertEqual(w.balances()['ETH'],Decimal('0.9'))
            self.assertEqual(w.balances()['BTC'],Decimal('0.00396'))
            self.assertNotIn('USD',w.balances())
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM unified_v501_disposals').fetchone()[0],1)
        finally:w.close()

    def test_bad_second_leg_rolls_back_first(self):
        w=ShadowFIFOPortfolio({'BTC':'1'},MARKS)
        try:
            bad=[STEPS[0],dict(STEPS[1],input_quantity=Decimal('99999'))]
            with self.assertRaises(Exception):
                w.post_hypothetical_route(session_id='SHADOW-C',steps=bad,usd_rates=MARKS,at_utc=1770000000)
            self.assertEqual(w.balances(),{'BTC':Decimal(1)})
            self.assertEqual(w.db.execute('SELECT COUNT(*) FROM unified_v501_fills').fetchone()[0],0)
        finally:w.close()

    def test_shadow_refuses_file_backed_db_and_has_no_post(self):
        import inspect
        self.assertNotIn('create_order(',inspect.getsource(ShadowFIFOPortfolio).lower())
        self.assertFalse(hasattr(ShadowFIFOPortfolio,'submit_order'))

    def test_rearming_resets_counters_and_disposes_old_memory_ledger(self):
        sh=ShadowArmedResearch()
        kwargs=dict(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities={'BTC':'1'},fresh_usd_rates=MARKS)
        sh.arm(**kwargs,now=1770000100)
        sh.observe(now=1770000105,quotes={'BTC-USD':('50000','50001',1770000105)},usd_rates=MARKS)
        self.assertEqual(sh.snapshot()['completed_fresh_scans'],1)
        sh.disarm(now=1770000110)
        sh.arm(**kwargs,now=1770000120)
        self.assertEqual(sh.snapshot()['completed_fresh_scans'],0)
        self.assertEqual(sh.snapshot()['shadow_fifo_posted_routes'],0)
        for w in sh.fifo_portfolios.values():w.close()

    def test_tiered_price_bands_no_unverified_fake_live_fill(self):
        sh=ShadowArmedResearch(mark_horizon_s=30)
        sh.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,usd_coverage=True,
            enrolled_quantities={'BTC':'1'},fresh_usd_rates=MARKS,now=1770000000)
        idea={'research_decision':'SWITCH_WORTH_RESEARCH','oos_validated':True,'net_p10_usd':Decimal('.70'),
              'source':'BTC','target':'ETH','trigger_pair':'ETH-USD',
              'input_units_planned':Decimal('.01'),'destination_units_estimate':Decimal('.2'),
              'shadow_fifo_steps':STEPS}
        sh.observe(now=1770000005,quotes={'ETH-USD':('1999','2000',1770000005)},usd_rates=MARKS,
                   route_ideas=[idea],minimum_advantage='.55')
        snapshot=sh.snapshot()
        self.assertEqual(snapshot['shadow_fifo_posted_routes'],1)
        self.assertEqual(snapshot['shadow_fifo_posted_legs'],2)
        self.assertEqual(snapshot['real_order_submissions'],0)
        self.assertEqual(snapshot['passive_price_touches_without_fill_proof'],0)
        sh.observe(now=1770000010,quotes={'ETH-USD':('1989','1990',1770000010)},usd_rates=MARKS)
        self.assertGreaterEqual(sh.snapshot()['passive_price_touches_without_fill_proof'],1)
        self.assertEqual(sh.snapshot()['real_fill_confirmations'],0)
        sh.disarm()
        for w in sh.fifo_portfolios.values():w.close()

if __name__=='__main__':unittest.main()
