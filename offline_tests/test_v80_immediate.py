"""T01/02/03/05/06/08: deterministic synthetic immediate math and evidence."""
from copy import deepcopy
from decimal import Decimal as D,localcontext
import unittest
from coincat_v80_immediate import evaluate,rank
from coincat_multicurrency import research_order,ResearchDepthError
from coincat_snowball import _liquidation_usd
from offline_tests.v80_fixtures import reference,synthetic_proof,NOW


class Immediate(unittest.TestCase):
    def test_positive_reference_gross_trade_fees_residual_and_independent_expectation(self):
        idea,q,rules=reference();r=evaluate(idea,q,rules,now=NOW)
        self.assertEqual(r['state'],'MODELED_POSITIVE_UNVERIFIED')
        self.assertTrue(r['positive_estimate']);self.assertFalse(r['strict'])
        step=r['frame']['idea']['shadow_fifo_steps'][0]
        self.assertEqual(step['output_quantity'],D('.03865608'))
        self.assertEqual(step['input_quantity'],D('.0019999995236904960'))
        self.assertEqual(r['w'],D('.5058318154752000000'))
        k=D('.9895135');residual=D('.002')-step['input_quantity']
        expected=step['output_quantity']*2600*k+residual*50000-D(100)*k
        self.assertAlmostEqual(r['l'],expected,places=23)
        with localcontext() as ctx:
            ctx.prec=60
            raw=D('.002')/(D('.0512')*D('1.0015')*D('1.009'))
            self.assertEqual((raw*2600-100).quantize(D('.00001')),D('.50583'))
            self.assertEqual(((raw*2600-100)*k).quantize(D('.00001')),D('.50053'))

    def test_live_optional_fields_and_forecasts_cannot_fabricate_qualification(self):
        idea,q,rules=reference();r=evaluate(idea,q,rules,now=NOW)
        proof=synthetic_proof(r)
        idea['forward_edge_evidence']={'state':'READY_EXPERIMENTAL','mean_relative_growth':'999'}
        live=evaluate(idea,q,rules,now=NOW,synthetic_evidence=proof)
        self.assertFalse(live['strict']);self.assertIn('CONNECTED_EVIDENCE_NOT_INTEGRATED',live['blockers'])
        offline=evaluate(idea,q,rules,now=NOW,synthetic_evidence=proof,allow_synthetic=True)
        self.assertTrue(offline['strict']);self.assertEqual(offline['evidence_origin'],'SYNTHETIC_OFFLINE')

    def test_negative_zero_and_liquidation_cannot_override_wallet_loss(self):
        idea,q,rules=reference()
        for price in ('2500','2530'):
            bad=dict(q);bad['ETH-USD']=(D(price),D(price)+D('.01'),NOW)
            idea['forward_edge_evidence']={'state':'READY_EXPERIMENTAL','mean_relative_growth':'1000'}
            r=evaluate(idea,bad,rules,now=NOW)
            self.assertFalse(r['strict']);self.assertFalse(r['positive_estimate']);self.assertLessEqual(r['w'],0)
        # Both directions at zero fee/slippage are tested directly by the
        # strict predicate's actual zero comparison in the next exact fixture.
        zero=deepcopy(idea);zero['shadow_fifo_steps'][0]['fee_rate_used']='0'
        qzero=dict(q,**{'ETH-USD':(D('2563.84'),D('2563.85'),NOW)})
        # With fees zero, the pre-round 1.0015*ask ETH cost equals its USD mark.
        z=evaluate(zero,qzero,rules,now=NOW)
        self.assertEqual(z['w'],0);self.assertFalse(z['positive_estimate'])

    def test_stale_missing_skew_future_wide_are_not_economic_losses(self):
        idea,q,rules=reference()
        variants=[]
        for stamp in (NOW-31,NOW+1,NOW-20):
            v=dict(q);v['ETH-USD']=(D(2600),D('2600.01'),stamp);variants.append(v)
        v=dict(q);v.pop('BTC-USD');variants.append(v)
        v=dict(q);v['ETH-USD']=(D(2600),D(2700),NOW);variants.append(v)
        for books in variants:
            with self.subTest(books=books):
                r=evaluate(idea,books,rules,now=NOW)
                self.assertEqual(r['state'],'NOT_PRICED');self.assertIsNone(r['w'])

    def test_independent_alternate_path_retry_and_cache_isolation(self):
        q={'AAA-BTC':(D('.01'),D('.01001'),NOW),'BTC-USD':(D(100),D('100.01'),NOW),
           'AAA-USDC':(D(1),D('1.001'),NOW),'USDC-USD':(D('.99'),D('.9901'),NOW)}
        cache={}
        a=_liquidation_usd('AAA',q,now=NOW,route_pair='AAA-BTC',fee=D('.009'),_fx_cache=cache)
        self.assertIsNotNone(a)
        self.assertEqual(a[0],D('.99')*D('.9895135')**2)
        b=_liquidation_usd('AAA',q,now=NOW,route_pair='AAA-USDC',fee=D('.009'),_fx_cache=cache)
        self.assertIsNotNone(b);self.assertNotEqual(a[0],b[0])
        q.pop('AAA-USDC')
        self.assertIsNone(_liquidation_usd('AAA',q,now=NOW,route_pair='AAA-BTC',fee=D('.009')))

    def test_depth_fee_currency_frame_and_rounding_checks(self):
        idea,q,rules=reference();base=evaluate(idea,q,rules,now=NOW);proof=synthetic_proof(base)
        for kind in ('missing_depth','insufficient_depth','wrong_currency','wrong_frame','missing_preview'):
            p=deepcopy(proof)
            if kind=='missing_depth':p['books'].pop('ETH-BTC')
            if kind=='insufficient_depth':p['books']['ETH-BTC']['asks'][0]['size']='.000001'
            if kind=='wrong_currency':p['previews'][0]['fee_currency']='USD'
            if kind=='wrong_frame':p['frame_id']='OTHER_FRAME'
            if kind=='missing_preview':p['previews']=[]
            r=evaluate(idea,q,rules,now=NOW,synthetic_evidence=p,allow_synthetic=True)
            self.assertTrue(r['positive_estimate'],kind);self.assertFalse(r['strict'],kind)
            self.assertEqual(r['state'],'MODELED_POSITIVE_UNVERIFIED')
        tight=deepcopy(rules);tight['ETH-BTC']['base_increment']='.1'
        r=evaluate(idea,q,tight,now=NOW);self.assertFalse(r['strict']);self.assertEqual(r['state'],'NOT_PRICED')

    def test_each_immediate_comparison_is_required_without_forward_override(self):
        # An extra destination liquidation hop exactly consumes an otherwise
        # positive wallet advantage. All products/prices here are invented.
        from coincat_multicurrency import evaluate_rotation
        q={'DST-SRC':(D('.9999'),D(1),NOW),'SRC-USD':(D('998.5'),D('998.51'),NOW),
           'DST-MID':(D('1001.5'),D('1001.51'),NOW),'MID-USD':(D(1),D('1.0001'),NOW)}
        rules={p:dict(product_id=p,product_type='SPOT',status='online',base_increment='.00000001',
                      base_min_size='.00000001',quote_min_size='.00000001') for p in q}
        def idea(books,qty,cap):
            raw=evaluate_rotation(source='SRC',target='DST',authorized_qty=qty,verified_available_qty=qty,
                balance_age_s=0,catalog=list(books),quotes=books,now=NOW,usd_per_order_cap=cap,
                product_rules=rules,fee_rate='0',max_legs=1)['routes'][0]
            return dict(source='SRC',target='DST',source_units=D(qty),route=raw['route'],sends_live_orders=False,
                shadow_fifo_steps=raw['steps'],input_units_planned=raw['input_units_planned'],
                research_size_cap_usd=D(cap),forward_edge_evidence={'state':'READY_EXPERIMENTAL','mean_relative_growth':'999'})
        x=idea(q,'1.0015','999.99775');zero=evaluate(x,q,rules,now=NOW)
        self.assertGreater(zero['w'],0);self.assertEqual(zero['l'],0);self.assertFalse(zero['positive_estimate'])
        q['DST-MID']=(D('1001.49'),D('1001.50'),NOW)
        neg=evaluate(x,q,rules,now=NOW)
        self.assertGreater(neg['w'],0);self.assertLess(neg['l'],0);self.assertFalse(neg['strict'])
        q={'DST-SRC':(D('.9999'),D(1),NOW),'SRC-MID':(D(1000),D('1000.01'),NOW),
           'DST-USD':(D('1001.49'),D('1001.50'),NOW),'MID-USD':(D(1),D('1.0001'),NOW)}
        rules={p:dict(product_id=p,product_type='SPOT',status='online',base_increment='.00000001',
                      base_min_size='.00000001',quote_min_size='.00000001') for p in q}
        neg=evaluate(idea(q,'1.0015','1001.5'),q,rules,now=NOW)
        self.assertLess(neg['w'],0);self.assertGreater(neg['l'],0);self.assertFalse(neg['positive_estimate'])

    def test_sub_ten_cent_gain_qualifies_only_with_complete_synthetic_evidence(self):
        idea,q,rules=reference(qty='.00002',cap='1')
        estimate=evaluate(idea,q,rules,now=NOW)
        self.assertGreater(estimate['w'],0);self.assertLess(estimate['w'],D('.1'))
        proof=synthetic_proof(estimate)
        r=evaluate(idea,q,rules,now=NOW,synthetic_evidence=proof,allow_synthetic=True)
        self.assertTrue(r['strict']);self.assertGreater(r['l'],0)

    def test_depth_walk_is_size_sensitive_and_can_erase_economics(self):
        idea,q,rules=reference();base=evaluate(idea,q,rules,now=NOW);proof=synthetic_proof(base)
        proof['books']['ETH-BTC']['asks']=[{'price':'.0512','size':'.00001'},{'price':'.055','size':'10'}]
        r=evaluate(idea,q,rules,now=NOW,synthetic_evidence=proof,allow_synthetic=True)
        self.assertFalse(r['strict']);self.assertEqual(r['state'],'ECONOMIC_NEGATIVE');self.assertLess(r['w'],0)

    def test_five_distinct_positive_routes_are_not_generic_wait_or_fifteen_trades(self):
        idea,q,rules=reference();ideas=[]
        # Distinct synthetic target products, three sizes per target.
        for i in range(5):
            name=f'A{i:02}';q[name+'-BTC']=q['ETH-BTC'];q[name+'-USD']=q['ETH-USD']
            for p in (name+'-BTC',name+'-USD'):rules[p]=dict(rules['ETH-BTC'],product_id=p)
            for fraction in ('1','.5','.1'):
                x=deepcopy(idea);x['target']=name;x['shadow_fifo_steps'][0]['pair']=name+'-BTC'
                x['research_size_cap_usd']=D(100)*D(fraction);x['route']=((name+'-BTC','BUY'),);ideas.append(x)
        ranked,summary=rank(ideas,q,rules,now=NOW,limit=20)
        self.assertEqual(summary['positive_unverified_routes'],5);self.assertEqual(summary['size_trials'],15)
        self.assertEqual(summary['negative_routes'],0);self.assertEqual(summary['strict_qualified'],0)
        self.assertTrue(all(x['selection_state']=='MODELED_POSITIVE_UNVERIFIED' for x in ranked))
