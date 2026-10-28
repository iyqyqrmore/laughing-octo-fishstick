"""T04/05/10: actual static discovery, planner, strict consumer and RAM P&L."""
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import unittest
from coincat_app import CoinCatApp
from coincat_v80_discovery import select_books
from coincat_v80_shadow import StrictImmediateShadow
from coincat_v701_transport import QuoteSnapshot
from coincat_v706_selection import ForwardCostLearner
from offline_tests.v80_fixtures import reference,synthetic_proof,NOW
from offline_tests import test_v703_chain_contract as legacy_harness


class StaticDiscovery(unittest.TestCase):
    def test_static_pairs_both_directions_no_usd_priority_and_bounded_rotation(self):
        pairs=['AAA-USD','AAA-BTC','AAA-ETH']
        quotes={'BTC-USD':(D(100),D('100.01'),NOW),'ETH-USD':(D(10),D('10.001'),NOW),
                'AAA-USD':(D(2),D('2.001'),NOW)}
        catalog=pairs+['BTC-USD','ETH-USD']
        rules={p:dict(product_type='SPOT',status='online',base_increment='.00000001',
                      base_min_size='.00000001',quote_min_size='.00000001') for p in catalog}
        seen=set();cursor=0
        for _ in range(12):
            plan=select_books(catalog,rules,{'USD','BTC','ETH','AAA'},quotes=quotes,now=NOW,cursor=cursor,max_routes=2)
            self.assertLessEqual(len(plan['books']),16);seen.update(plan['directions']);cursor=plan['next_cursor']
        self.assertIn(('AAA-BTC','BUY','BTC','AAA'),seen)
        self.assertIn(('AAA-ETH','BUY','ETH','AAA'),seen)
        self.assertIn(('AAA-USD','SELL','AAA','USD'),seen)
        self.assertEqual(len(seen),10)

    def test_complete_dependencies_and_restricted_products(self):
        _,q,rules=reference()
        plan=select_books(list(q),rules,{'BTC'},quotes={},now=NOW)
        self.assertTrue({'ETH-BTC','ETH-USD','BTC-USD'}<=set(plan['books']))
        rules['ETH-BTC']['view_only']=True
        excluded=select_books(list(q),rules,{'BTC'},quotes=q,now=NOW)
        self.assertNotIn('ETH-BTC',excluded['books'])

    def fixture(self,folder):
        app,clock,text,fetch,rows=legacy_harness.SyntheticWholeChain.fixture(self,folder)
        for wallet in app.experimental_shadow.fifo_portfolios.values():wallet.close()
        idea,quotes,rules=reference()
        app.catalog=list(quotes);app.broker.catalog_product_rules=rules
        app.current_balances={'BTC':'.002'};rows[:]=[{'asset':'BTC','remaining_qty':'.002','enabled':1}]
        app.stream_research=NS(rank_for_rest_scout=lambda *a,**kw:[],snapshot=lambda **kw:{'rows':[]})
        app.experimental_shadow=StrictImmediateShadow(experimental=True,allow_synthetic_evidence=True)
        app.experimental_shadow.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,
            usd_coverage=True,enrolled_quantities=app.current_balances,
            fresh_usd_rates={'BTC':'50000','USD':'1'},now=NOW-1)
        self.addCleanup(lambda:[w.close() for w in app.experimental_shadow.fifo_portfolios.values()])
        app._experimental_model_balances=dict(app.current_balances)
        app.forward.selection=ForwardCostLearner(app.forward.path)
        app._manual_budget_saved.update(per_order_usd='100',added_exposure_usd='100',daily_buy_usd='100000')
        fetch=Mock(side_effect=lambda p,**kw:QuoteSnapshot(p,quotes[p][0],quotes[p][1],clock[0],clock[0],1))
        return app,clock,quotes,rules,fetch

    def test_actual_zero_momentum_cold_producer_positive_unverified_then_synthetic_ram_fifo(self):
        with TemporaryDirectory() as folder:
            app,clock,quotes,rules,fetch=self.fixture(folder)
            app.shutdown=False;app._fast_next_at=0
            app._connection_requested=app._connection_in_progress=False
            app._fill_sync_faulted=False;app.broker.ledger=NS(pending=lambda:[])
            self.assertTrue(CoinCatApp._fast_due(app))
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                payload=app._fast_cycle()
                self.assertEqual(payload['state'],'RESEARCHED',payload.get('reason'))
                self.assertGreater(payload['immediate_funnel']['positive_unverified_routes'],0)
                best=payload['plan']['ideas'][0]
                self.assertEqual((best['source'],best['target']),('BTC','ETH'))
                self.assertEqual(app._apply_fast_experimental(payload),0)
                self.assertEqual(app.experimental_shadow.model_balances(),{'BTC':D('.002')})
                clock[0]+=1
                r=best['immediate_assessment'];app.experimental_shadow.synthetic_evidence[r['frame']['id']]=synthetic_proof(r)
                self.assertEqual(app._apply_fast_experimental(payload),1)
                wallet=app.experimental_shadow.fifo_portfolios['TAKER_ASK']
                self.assertTrue(wallet.quantity_parity())
                value=wallet.mark_vs_hold({'BTC':'50000','ETH':'2600','USD':'1'})
                self.assertAlmostEqual(value['delta_usd'],D('.5058318154752'),places=20)
                self.assertGreater(wallet.fees_estimated_usd,0)
                # The same stale payload cannot be charged again after its
                # original model inventory has been superseded.
                clock[0]+=1
                self.assertEqual(app._apply_fast_experimental(payload),0)
            app.broker.submit.assert_not_called()
            self.assertEqual(app.forward.selection.summary()['observations'],{})

    def test_newly_received_coin_funds_next_actual_qualified_conversion(self):
        with TemporaryDirectory() as folder:
            app,clock,q,rules,fetch=self.fixture(folder)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                first=app._fast_cycle();best=first['plan']['ideas'][0];r=best['immediate_assessment']
                app.experimental_shadow.synthetic_evidence[r['frame']['id']]=synthetic_proof(r)
                self.assertEqual(app._apply_fast_experimental(first),1)
                self.assertNotIn('ETH',app.current_balances)
                q.update({'SOL-ETH':(D('.009999'),D('.01'),NOW),'SOL-USD':(D(30),D('30.001'),NOW)})
                for p in ('SOL-ETH','SOL-USD'):rules[p]=dict(rules['ETH-BTC'],product_id=p)
                app.catalog=list(q)
                posted=False
                for _ in range(6):
                    clock[0]+=1;payload=app._fast_cycle()
                    candidates=[i for i in payload.get('plan',{}).get('ideas',()) if i.get('source')=='ETH'
                        and i.get('target')=='SOL' and i.get('immediate_assessment',{}).get('positive_estimate')]
                    if not candidates:continue
                    r=candidates[0]['immediate_assessment']
                    app.experimental_shadow.synthetic_evidence[r['frame']['id']]=synthetic_proof(r)
                    posted=app._apply_fast_experimental(payload)==1
                    if posted:break
                self.assertTrue(posted)
                self.assertGreater(app.experimental_shadow.model_balances()['SOL'],0)
                self.assertEqual(app.experimental_shadow.fifo_posted,2)
                self.assertTrue(app.experimental_shadow.fifo_portfolios['TAKER_ASK'].quantity_parity())
            app.broker.submit.assert_not_called()
