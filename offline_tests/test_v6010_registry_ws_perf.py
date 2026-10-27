"""v60.10 isolated trading-universe and nonblocking market depth guards."""
import ast,time,unittest
from pathlib import Path
from decimal import Decimal
from coincat_v6010_registry import spot_registry,one_order_catalog,eligible_product
from coincat_v6010_microstructure import top_of_book,depth_advisory,bounded_readonly_probe
from coincat_multicurrency import evaluate_rotation
from coincat_market_stream import PublicTickerTape

NOW=1800000000
RULE={'base_increment':'.000001','base_min_size':'.001','quote_min_size':'.001',
      'product_type':'SPOT','view_only':False, 'trading_disabled':False}
class Registry(unittest.TestCase):
 def test_pagination_counts_reconcile_and_fiat_pairs_included(self):
  products=[dict(RULE,product_id='ADA-USDC'),dict(RULE,product_id='SOL-USD'),
     dict(RULE,product_id='ADA-BTC'), dict(RULE,product_id='ADA-USDC'),
     dict(RULE,product_id='LOCK-USD',trading_disabled=True),
     dict(RULE,product_id='FUT-USD',product_type='FUTURE'),
     dict(RULE,product_id='X-USD',view_only=True)]
  ids,rules,audit=spot_registry(products)
  self.assertEqual(ids,['ADA-BTC','ADA-USDC','SOL-USD'])
  self.assertEqual(audit['raw_count'],7)
  self.assertEqual(audit['eligible_count'],3)
  self.assertEqual(audit['filtered_count'],4)
  self.assertEqual(audit['usd_usdc'],2)
  self.assertEqual(audit['reject_reasons']['RESTRICTED'],2)
  self.assertEqual(audit['reject_reasons']['DUPLICATE_ID'],1)
  self.assertEqual(len(one_order_catalog(ids,rules)),3)
 def test_restricted_modes_not_market_executable(self):
  for flag in ('view_only','trading_disabled','is_disabled','cancel_only','limit_only','post_only','auction_mode'):
   with self.subTest(flag=flag):self.assertFalse(eligible_product(dict(RULE,product_id='ADA-USDC',**{flag:True})))
 def test_usdc_to_ada_one_order_no_hidden_usd_bridge(self):
  result=evaluate_rotation(source='USDC',target='ADA',authorized_qty='20',verified_available_qty='20',
    balance_age_s=2,catalog=['ADA-USDC','ADA-USD'],
    quotes={'ADA-USDC':('.90','.9005',NOW),'ADA-USD':('.9001','.9008',NOW)},
    now=NOW,usd_per_order_cap='20',product_rules={'ADA-USDC':RULE,'ADA-USD':RULE},
    fee_rate='.009',max_legs=1,crypto_only=False)
  self.assertEqual(result['state'],'RESEARCH ONLY')
  self.assertEqual(result['routes'][0]['route'],(('ADA-USDC','BUY'),))
  self.assertEqual(len(result['routes'][0]['steps']),1)
 def test_no_synthetic_sol_to_ada_without_direct_listing(self):
  r=evaluate_rotation(source='SOL',target='ADA',authorized_qty='1',verified_available_qty='1',
   balance_age_s=2,catalog=['SOL-USD','ADA-USD'],
   quotes={'SOL-USD':('100','100.1',NOW),'ADA-USD':('.90','.91',NOW)},now=NOW,
   usd_per_order_cap='100',product_rules={'SOL-USD':RULE,'ADA-USD':RULE},fee_rate='.009',max_legs=1)
  self.assertFalse(r['routes'])
 def test_broad_ws_is_one_public_ticker_batch(self):
  from coincat_market_stream import PUBLIC_CHANNEL,PublicTickerTape
  self.assertEqual(PUBLIC_CHANNEL,'ticker_batch')
  tape=PublicTickerTape()
  tape.set_pairs(['ADA-USDC','SOL-USD','ADA-BTC'])
  self.assertEqual(tape.status()['pairs'],3)
class Depth(unittest.TestCase):
 def test_authenticated_top_book_and_depth(self):
  p='ADA-USDC'
  top={'pricebooks':[{'product_id':p,'bids':[{'price':'.9','size':'100'}],
       'asks':[{'price':'.91','size':'200'}]}]}
  self.assertEqual(top_of_book(top,p)['bid'],Decimal('.9'))
  book={'pricebook':{'product_id':p,'bids':[{'price':'.9','size':'100'}],
          'asks':[{'price':'.91','size':'200'}]}}
  self.assertLess(depth_advisory(book,p)['imbalance'],Decimal(0))
 def test_crossed_or_wrong_pair_fail_closed(self):
  with self.assertRaises(ValueError):top_of_book({'pricebooks':[{'product_id':'BTC-USD','bids':[{'price':'2','size':'1'}],
    'asks':[{'price':'1','size':'1'}]}]},'BTC-USD')
  with self.assertRaises(ValueError):depth_advisory({'pricebook':{'product_id':'SOL-USD'}},'ADA-USDC')
 def test_market_probe_has_no_orders(self):
  class Dummy:
   def get_best_bid_ask(self,**kwargs):
    return {'pricebooks':[{'product_id':'ADA-USDC','bids':[{'price':'1','size':'1'}],
      'asks':[{'price':'1.01','size':'1'}]}]}
   def get_product_book(self,**kwargs):
    return {'pricebook':{'product_id':'ADA-USDC','bids':[{'price':'1','size':'1'}],
      'asks':[{'price':'1.01','size':'1'}]}}
  x=bounded_readonly_probe(Dummy(),'ADA-USDC')
  self.assertEqual(x['extra_gets'],2)
  self.assertFalse(x['order_authorized'])
 def test_gui_scan_does_not_wait_on_secondary_market_book_get(self):
  source=(Path(__file__).resolve().parents[1]/'app/coincat_app.py').read_text()
  tree=ast.parse(source)
  self.assertIn("name='CoinCatReadOnlyDepthAdvisory'",source)
  self.assertIn('daemon=True',source)
  self.assertNotIn('result[\'authenticated_market_probe\']=bounded_readonly_probe(',source)
 def test_no_real_order_submit_in_v6010_modules(self):
  for name in ('coincat_v6010_registry.py','coincat_v6010_microstructure.py'):
   src=(Path(__file__).resolve().parents[1]/'app'/name).read_text()
   self.assertNotIn('create_order(',src)
if __name__=='__main__':unittest.main()
