"""Synthetic read-only ETH measurement, reserve proposals and passive advice."""
import ast
import hashlib
from copy import deepcopy
from decimal import Decimal as D, localcontext
from pathlib import Path
from unittest.mock import patch
import unittest

from coincat_eth_farmer import measure_eth, reserve_preview, ReservePolicy
from coincat_settings_advisor import settings_advice, DEFAULT_NOTE
from coincat_multicurrency import research_order
from coincat_passive_lab import PassiveLab
from offline_tests.test_v91_full_balance import market, scan, NOW
from offline_tests import test_v91_scanner_gui as gui
from coincat_scanner import Scanner


def measurement(*, result=None, balances=None, **changes):
    q, rules = market()
    args = dict(result=scan() if result is None else result,
        balances={'BTC': D('.002')} if balances is None else balances,
        quotes=q, rules=rules, catalog=list(q), now=NOW, balances_at=NOW,
        fee_rate=D('.009'))
    args.update(changes)
    return measure_eth(**args)


class ETHMeasurement(unittest.TestCase):
    def test_two_return_legs_use_actual_listed_pairs_and_each_leg_costs_once(self):
        q,rules=market();q.pop('ETH-BTC');q['SOL-USD']=(D(100),D('100.01'),NOW)
        rules['SOL-USD']=dict(rules['BTC-USD'],product_id='SOL-USD')
        value=measurement(result={'ranked':[]},balances={'SOL':D(2)},quotes=q,rules=rules,catalog=list(q))
        orders=value['hold']['orders']
        self.assertEqual([(o['pair'],o['side']) for o in orders],[('SOL-USD','SELL'),('ETH-USD','BUY')])
        self.assertEqual(orders[1]['input_asset'],orders[0]['output_asset'])
        self.assertLessEqual(orders[1]['input_quantity'],orders[0]['output_quantity'])
        self.assertEqual(value['hold']['modeled_eth_proceeds'],orders[1]['output_quantity'])
        self.assertEqual(orders[-1]['output_asset'],'ETH')
        self.assertTrue(all(o['fee_rate_used']==D('.009') for o in orders))

    def test_vet_to_btc_entry_requires_costed_btc_to_eth_before_eth_proceeds(self):
        # Synthetic listed topology, not a claim that Coinbase lists VET-BTC.
        q,rules=market();q['VET-BTC']=(D('.00000042'),D('.0000004201'),NOW)
        rules['VET-BTC']=dict(rules['BTC-USD'],product_id='VET-BTC')
        with localcontext() as ctx:
            ctx.prec=60
            entry=research_order(pair='VET-BTC',side='SELL',available=D(1000),
                cap=D(21),usd_rate=D('.021'),book=q['VET-BTC'],product_rules=rules,
                fee=D('.009'),slip=D('.0015'))
        best=dict(source='VET',target='BTC',spent=entry['input_quantity'],received=entry['output_quantity'],
                  frame={'dependencies':('VET-BTC','BTC-USD')})
        value=measurement(result={'ranked':[],'best':best},balances={'VET':D(1000)},
            quotes=q,rules=rules,catalog=list(q))
        hold=value['hold']['orders'];closed=value['switch']['orders']
        self.assertEqual([(r['input_asset'],r['output_asset']) for r in hold],[('VET','BTC'),('BTC','ETH')])
        self.assertEqual(hold[0],entry)
        self.assertEqual([(r['input_asset'],r['output_asset']) for r in closed],[('BTC','ETH')])
        self.assertLessEqual(closed[0]['input_quantity'],entry['output_quantity'])
        self.assertEqual(value['switch']['modeled_eth_proceeds'],closed[0]['output_quantity'])
        self.assertTrue(all(r['fee_rate_used']==D('.009') and r['modeled_slippage_fraction']==D('.0015') for r in hold+closed))
        self.assertIsNone(value['return_advantage_eth'])  # Retained BTC dust is still unconverted.
        self.assertFalse(value['live_order_permission'])

    def test_intermediate_btc_without_bounded_eth_return_is_not_counted_as_eth(self):
        # BTC -> VET -> USD -> ETH would require three return legs; the current
        # model supports two. A USD mark alone cannot invent an ETH conversion.
        _,template=market();q={'VET-BTC':(D('.00000042'),D('.0000004201'),NOW),
            'VET-USD':(D('.02'),D('.02001'),NOW),'ETH-USD':(D(2600),D('2600.01'),NOW)}
        rules={p:dict(template['BTC-USD'],product_id=p) for p in q}
        value=measurement(result={'ranked':[]},balances={'BTC':D('.002')},quotes=q,rules=rules,catalog=list(q))
        self.assertEqual(value['hold']['orders'],[])
        self.assertEqual(value['hold']['unconverted_native'],{'BTC':D('.002')})
        self.assertEqual(value['hold']['modeled_eth_proceeds'],0)
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])
        self.assertIsNone(value['return_advantage_eth'])
        self.assertEqual(value['state'],'UNKNOWN')

    def test_common_eth_divisor_preserves_every_usd_rank_without_input_mutation(self):
        result=scan(); before=deepcopy(result)
        value=measurement(result=result)
        with localcontext() as ctx:
            ctx.prec=60
            expected=[row['w']/D(2600) for row in result['ranked']]
        actual=[value['w_eth_by_frame'][row['frame']['id']] for row in result['ranked']]
        self.assertEqual(actual,expected)
        self.assertEqual(actual,sorted(actual,reverse=True))
        self.assertEqual(result,before)
        self.assertFalse(value['live_order_permission'])

    def test_eth_units_and_usd_secondary_mark_are_separate_from_earnings(self):
        value=measurement(result={'ranked':[]},balances={'ETH':D(2)})
        self.assertEqual(value['actual_available_eth'],D(2))
        self.assertEqual(value['hold']['estimated_recoverable_eth'],D(2))
        self.assertEqual(value['portfolio_usd_mark'],D(5200))
        for key in ('earned_eth','settled_eth','protected_eth','cashflow_adjusted_gain_eth'):
            self.assertIsNone(value[key])

    def test_deposit_manual_swap_withdrawal_and_price_move_never_become_earned_eth(self):
        q,rules=market()
        for balances in ({'ETH':D(1)},{'ETH':D(2)},{'USD':D(2600)},{'ETH':D('.5')}):
            for price in (D(1300),D(2600),D(5200)):
                books=dict(q,**{'ETH-USD':(price,price+D('.01'),NOW)})
                value=measurement(result={'ranked':[]},balances=balances,quotes=books,rules=rules)
                self.assertIsNone(value['earned_eth'])
                self.assertIsNone(value['cashflow_adjusted_gain_eth'])

    def test_unknown_initial_asset_does_not_become_zero_or_a_complete_total(self):
        value=measurement(result={'ranked':[]},balances={'ETH':D(1),'MYST':D(7)})
        self.assertEqual(value['state'],'UNKNOWN')
        self.assertIsNone(value['portfolio_usd_mark'])
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])
        self.assertEqual(value['hold']['unconverted_native'],{'MYST':D(7)})
        self.assertEqual(value['hold']['modeled_eth_proceeds'],D(1))

    def test_missing_eth_reference_and_stale_balances_are_unknown(self):
        q,rules=market();del q['ETH-USD']
        value=measurement(quotes=q,rules=rules)
        self.assertIsNone(value['reference_eth_usd'])
        self.assertEqual(value['w_eth_by_frame'],{})
        stale=measurement(balances_at=NOW-121)
        self.assertIsNone(stale['actual_available_eth'])
        self.assertEqual(stale['reason'],'AVAILABLE_BALANCES_STALE_OR_UNOBSERVED')

    def test_stale_wide_future_or_negative_eth_book_never_supplies_a_reference(self):
        q,rules=market()
        for book in ((D(2600),D(2601),NOW-31),(D(2600),D(2700),NOW),
                     (D(2600),D(2601),NOW+1),(D(-1),D(2),NOW)):
            value=measurement(quotes=dict(q,**{'ETH-USD':book}),rules=rules)
            self.assertIsNone(value['reference_eth_usd'])

    def test_return_to_eth_skew_does_not_publish_proceeds_as_complete(self):
        q,rules=market();q['ETH-BTC']=(q['ETH-BTC'][0],q['ETH-BTC'][1],NOW-17)
        value=measurement(result={'ranked':[]},quotes=q,rules=rules)
        self.assertEqual(value['reason'],'ETH_RETURN_PRICE_SKEW')
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])
        self.assertIsNone(value['hold']['modeled_eth_proceeds'])

    def test_unconverted_dust_retained_and_costs_exactly_once_per_return_leg(self):
        value=measurement(result={'ranked':[]})
        hold=value['hold'];order=hold['orders'][0];q,rules=market()
        with localcontext() as ctx:
            ctx.prec=60
            expected=research_order(pair='ETH-BTC',side='BUY',available=D('.002'),
                cap=D(100),usd_rate=D(50000),book=q['ETH-BTC'],product_rules=rules,fee=D('.009'))
        self.assertEqual(order,expected)
        self.assertEqual(hold['modeled_eth_proceeds'],order['output_quantity'])
        self.assertEqual(hold['unconverted_native']['BTC'],D('.002')-order['input_quantity'])
        self.assertIsNone(hold['estimated_recoverable_eth'])

    def test_full_size_maximum_is_not_fractionally_fitted_and_tiny_size_not_enlarged(self):
        q,rules=market();rules['ETH-BTC']['base_max_size']='.0001'
        value=measurement(result={'ranked':[]},quotes=q,rules=rules)
        self.assertEqual(value['hold']['orders'],[])
        self.assertEqual(value['hold']['unconverted_native']['BTC'],D('.002'))
        rules['ETH-BTC'].pop('base_max_size');rules['ETH-BTC']['base_min_size']='1'
        value=measurement(result={'ranked':[]},balances={'BTC':D('.00000000000001')},quotes=q,rules=rules)
        self.assertEqual(value['hold']['orders'],[])
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])

    def test_stablecoin_without_observed_market_is_not_assumed_usd_or_eth(self):
        value=measurement(result={'ranked':[]},balances={'USDC':D(100)})
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])
        self.assertIsNone(value['portfolio_usd_mark'])
        self.assertEqual(value['hold']['unconverted_native'],{'USDC':D(100)})

    def test_exclusions_and_product_disable_prevent_return_conversions(self):
        value=measurement(result={'ranked':[]},excluded={'BTC'})
        self.assertEqual(value['hold']['orders'],[])
        q,rules=market();rules['ETH-BTC']['view_only']=True
        value=measurement(result={'ranked':[]},quotes=q,rules=rules)
        self.assertTrue(all(o['pair']!='ETH-BTC' for o in value['hold']['orders']))

    def test_fixed_shortest_lexical_path_does_not_chase_more_profitable_alternatives(self):
        q,rules=market()
        # USD route has two legs while the listed BTC->ETH BUY is direct.
        value=measurement(result={'ranked':[]})
        permuted=measurement(result={'ranked':[]},quotes=dict(reversed(list(q.items()))),
            rules=rules,catalog=list(reversed(q)))
        self.assertEqual(value,permuted)
        self.assertEqual([o['pair'] for o in value['hold']['orders']],['ETH-BTC'])

    def test_round_trip_does_not_assume_an_eth_gain_even_when_usd_mark_w_is_positive(self):
        value=measurement()
        # Positive mark W can exist without a completely convertible ETH return.
        self.assertTrue(value['w_eth_by_frame'])
        self.assertIsNone(value['return_advantage_eth'])
        self.assertIsNone(value['earned_eth'])

    def test_invalid_fees_quantities_and_slippage_fail_closed(self):
        for changes in ({'fee_rate':None},{'fee_rate':D('.05')},
                        {'balances':{'ETH':D('NaN')}},{'balances':{'ETH':D(-1)}},
                        {'slippage_bps':D(51)}):
            value=measurement(**changes)
            self.assertEqual(value['state'],'UNKNOWN')
            self.assertIsNone(value['return_advantage_eth'])


class ReserveCalculator(unittest.TestCase):
    def test_default_policy_is_only_a_pending_proposal_without_a_fixed_reference(self):
        result=reserve_preview()
        self.assertEqual(result['state'],'PENDING_REFERENCE')
        self.assertFalse(result['assets_earmarked'])
        self.assertIsNone(result['actual_reserved_eth'])

    def test_ten_twenty_ten_uses_an_explicit_fixed_eth_reference(self):
        value=reserve_preview(fixed_reference=D(2000))
        self.assertEqual(value['initial_target_eth'],D('.005'))
        self.assertEqual(value['growth_step_eth'],D('.01'))
        self.assertEqual(value['harvest_per_step_eth'],D('.005'))
        self.assertNotIn('scenario_new_milestones',value)

    def test_multiple_crossings_consumed_milestones_and_loss_recovery(self):
        for earned,consumed,due in (('.035',0,3),('.035',3,0),('.005',3,0),
                                    ('-.01',3,0),('.039',3,0),('.04',3,1)):
            value=reserve_preview(fixed_reference=D(2000),hypothetical_earned_eth=D(earned),
                consumed_milestones=consumed)
            self.assertEqual(value['scenario_new_milestones'],due)
            self.assertEqual(value['scenario_harvest_eth'],D('.005')*due)
            self.assertIsNone(value['actual_earned_eth'])
            self.assertFalse(value['assets_earmarked'])

    def test_underfunded_scenario_never_auto_buys_or_banks_non_eth_gains(self):
        value=reserve_preview(fixed_reference=D(2000),hypothetical_earned_eth=D('.035'),
            hypothetical_settled_eth=D('.001'))
        self.assertEqual(value['state'],'SCENARIO_UNDERFUNDED_NO_AUTO_BUY')
        self.assertIsNone(value['actual_reserved_eth'])

    def test_reset_is_a_new_scenario_not_a_replayed_actual_harvest(self):
        a=reserve_preview(fixed_reference=D(2000),hypothetical_earned_eth=D('.025'),consumed_milestones=2)
        b=reserve_preview(fixed_reference=D(2000),hypothetical_earned_eth=D('.025'),consumed_milestones=0)
        self.assertEqual(a['scenario_new_milestones'],0)
        self.assertEqual(b['scenario_new_milestones'],2)
        self.assertFalse(b['assets_earmarked'])
        self.assertEqual(a,reserve_preview(fixed_reference=D(2000),hypothetical_earned_eth=D('.025'),consumed_milestones=2))

    def test_fractional_units_and_policy_input_validation(self):
        value=reserve_preview(ReservePolicy(D('.01'),D('.03'),D('.01')),fixed_reference=D(100000))
        self.assertEqual(value['initial_target_eth'],D('.0000001'))
        for kwargs in ({'fixed_reference':D(-1)},{'consumed_milestones':-1},
                       {'consumed_milestones':True},{'fixed_reference':D('NaN')}):
            with self.assertRaises(ValueError):reserve_preview(**kwargs)
        with self.assertRaises(ValueError):reserve_preview(ReservePolicy(growth_step_usd=D(0)))


class PassiveAdvisor(unittest.TestCase):
    def test_seven_protected_modules_exactly_match_the_verified_v91_baseline(self):
        hashes={
            'coincat_live.py':'582744bde0497df22c8bad1d6092c6092bb64c99d171f783eec7ac5f86d3ffe4',
            'coincat_unified_fifo_v501.py':'c2cc83616bc3ebe4df04b3b9355ecddd2dd3e2b16f86987c100119ad9103493a',
            'coincat_state_v50.py':'93cf2add1878c3f2b48221eb53a9a556270ee8672e2a0746fed1c60ccb3e984b',
            'coincat_data_transfer.py':'b797413e3108bfb45a4986514ae2ded15e907b7c8edcb3e34217c2efe04be216',
            'coincat_inventory_lots.py':'72b06c37a99df2131e96f1336872c4289a81b33974e833703988e90050e681b7',
            'coincat_verified_cross_fills.py':'49cc8fd6ea71553b48c85ebc6cc48166761c7f9bd0349c312cc5dcf707fbe130',
            'coinbase_account.py':'ba6148242d86243135670dbf1c20435ec54cf5ff6f07976a68c09bddb479c0e0'}
        root=Path(__file__).resolve().parents[1]/'app'
        for name,expected in hashes.items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected,name)

    def test_unknown_economics_keep_conservative_text_and_no_setting_change(self):
        result={'priced_directions':500,'positive_directions':500,'fetch_ms':1}
        original=deepcopy(result);text=settings_advice(result)
        self.assertIn(DEFAULT_NOTE,text)
        self.assertIn('INSUFFICIENT',text)
        self.assertIn('Manual decision only / no setting changed',text)
        self.assertEqual(result,original)

    def test_cadence_recommendation_cites_current_suggested_units_evidence_and_tradeoff(self):
        text=settings_advice({'fetch_ms':12000},scan_interval_s=D(5))
        for phrase in ('Current 5 s','suggested 24 s','Measured','PRELIMINARY',
                       'one pass','miss short-lived','no setting changed'):
            self.assertIn(phrase,text)
        self.assertNotIn('SUPPORTED',text)

    def test_no_advisor_or_calculator_execution_mutation_or_network_dependencies(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('coincat_eth_farmer.py','coincat_settings_advisor.py','coincat_mixer.py'):
            tree=ast.parse((root/'app'/name).read_text(encoding='utf-8'))
            forbidden={'submit','create_order','preview_order','cancel_orders','transfer','arm',
                       'save_encrypted','approve_all','set_asset_enabled','write_text','execute','connect'}
            calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
            self.assertFalse(calls & forbidden,name)
            imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
            self.assertFalse(imports & {'coincat_live','coincat_scanner','requests','coinbase.rest'},name)

    def test_eth_future_comparisons_keep_missing_reference_counts_distinct(self):
        q,rules=market();result=scan();lab=PassiveLab()
        lab.observe(result,q,now=NOW)
        future={p:(b[0],b[1],NOW+300) for p,b in q.items()}
        lab.observe({'ranked':[]},future,now=NOW+300)
        self.assertGreater(lab.eth_counts['300_ABOVE_HOLD'],0)
        self.assertEqual(sum(v for k,v in lab.eth_counts.items() if k.startswith('300_')),
                         lab.counts['300_ABOVE_HOLD']+lab.counts['300_NOT_ABOVE_HOLD'])
        lab=PassiveLab();lab.observe(result,q,now=NOW)
        lab.observe({'ranked':[]},{},now=NOW+421)
        self.assertGreater(lab.eth_counts['300_MISSED'],0)
        self.assertEqual(lab.eth_counts['300_NOT_ABOVE_HOLD'],0)


class MixerGUI(unittest.TestCase):
    setUp = gui.SimpleGUI.setUp
    def test_exact_entry_fader_keyboard_reset_invalid_input_and_labels(self):
        self.root.update()
        controls=self.app.mixer.controls
        self.assertEqual(len(controls),6)
        fader=controls['initial_usd']
        fader.text.set('12.345');fader._entered()
        self.assertEqual(fader.value,D('12.345'))
        self.assertAlmostEqual(fader.scale.get(),12.345)
        fader._step(1);self.assertEqual(fader.value,D('13.345'))
        fader._slide('17.6');self.assertEqual(fader.text.get(),'18')
        fader.text.set('NaN');fader._entered()
        self.assertEqual(fader.value,D(18));self.assertIn('Invalid',fader.error.get())
        fader.set(fader.spec.default);self.assertEqual(fader.value,D(10))
        self.assertIn('default 10',fader.marker.get())
        self.assertTrue(fader.entry.cget('takefocus')!='0')
        self.assertLessEqual(self.app.mixer.winfo_reqwidth(),self.root.winfo_width())

    def test_mixer_changes_are_ram_only_and_never_change_ranking_or_private_records(self):
        app=self.app;client=gui.FakeClient()
        app.scanner=Scanner(app.ledger,client,app.fees,app.market)
        before=gui.ledger_dump(app.ledger);app.scanner.refresh(now=NOW)
        result=app.scanner.scan(now=NOW,collect=gui.collector(client))
        app.last_result=result;app._render(result);original=deepcopy(result)
        for key,value in (('reference_usd',D(2000)),('initial_usd',D(20)),
                          ('slippage_bps',D(30)),('scan_interval_s',D(20))):
            app.mixer.controls[key].set(value)
        self.assertEqual(result,original)
        self.assertEqual(before,gui.ledger_dump(app.ledger))
        self.assertFalse(app.reserve_calculation['assets_earmarked'])
        self.assertIsNone(app.reserve_calculation['actual_reserved_eth'])
        self.assertIn('UNKNOWN',app.eth_details.get())
        self.assertIn('no funds earmarked',app.reserve_text.get())

    def test_export_redacts_all_eth_quantities_and_keeps_eight_sections(self):
        from coincat_simple_diagnostics import make_report
        self.app.eth_measurement={'state':'UNKNOWN','actual_available_eth':D('98765.432198765'),
            'hold':{'modeled_eth_proceeds':D('23456.78923456'),'unconverted_native':{'BTC':D('12345.678912345')}}}
        report=make_report(self.app,now=NOW)
        self.assertIn('COMPLETE (8/8)',report)
        for raw in ('98765.432198765','23456.78923456','12345.678912345'):
            self.assertNotIn(raw,report)
        self.assertIn('manual_mixer_proposal',report)
        self.assertIn('UNKNOWN_NO_EARMARKING',report)
