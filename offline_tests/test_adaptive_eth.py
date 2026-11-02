"""Synthetic falsification of conditional research, never exchange/fill evidence."""
from copy import deepcopy
from decimal import Decimal as D, localcontext
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from coincat_adaptive_eth import (Frame, candidate_graph, closed_routes, estimate_path,
    ResearchFunds, ForwardStudy, recoverable_inventory, scoreboard, public_summary, validate_public)
from coincat_working_allocation import AllocationRow
from coincat_watchlist import WATCH_PAIRS
from coincat_monitor import capture, encode, read_snapshot, SCHEMA
from coincat_monitor_server import HTML, JS
from offline_tests.test_v100_monitor import app_fixture
from offline_tests.test_native_receipts import NOW

ETH_BTC = ('ETH-BTC', 'SELL', 'ETH', 'BTC')
BTC_ETH = ('ETH-BTC', 'BUY', 'BTC', 'ETH')
BTC_SOL = ('SOL-BTC', 'BUY', 'BTC', 'SOL')
SOL_BTC = ('SOL-BTC', 'SELL', 'SOL', 'BTC')
SOL_ETH = ('SOL-ETH', 'SELL', 'SOL', 'ETH')


def inputs(at=NOW, fee='0', changes=None, evidence=True):
    rules = {p: dict(product_id=p, product_type='SPOT', status='online', view_only=False,
        base_increment='0.00000001', quote_increment='0.00000001', price_increment='0.00000001',
        base_min_size='0.00000001', quote_min_size='0.00000001') for p in WATCH_PAIRS}
    quotes = {p: (D(1), D(1), at) for p in WATCH_PAIRS}
    quotes.update(changes or {})
    tier = dict(fresh=True, captured_at=at, maker=D(fee), taker=D(fee))
    depth = {}; units = {}
    if evidence:
        for p, book in quotes.items():
            for side, index in (('BUY', 1), ('SELL', 0)):
                depth[p, side] = dict(pair=p, side=side, observed_at=book[2],
                    levels=[dict(price=book[index], size=D(100))])
                units[p, side] = dict(currency=p.split('-')[1], verified=True, observed_at=book[2])
    return dict(at=at, _catalog=WATCH_PAIRS, _rules=rules, _quotes=quotes,
                _tier=tier, _depth=depth, _fee_units=units)


def frame(**changes):
    return Frame(**inputs(**changes))


def assume(funds, reference, leg, observation=None, quantity=D(1)):
    result = funds.reserve(reference, leg=leg, quantity=quantity,
                           frame=observation or frame(), slippage_bps=D(0))
    r = result['receipts'][0]
    funds.assume_fill(reference, classification='SIMULATED_ASSUMPTION',
        input_quantity=r['input_quantity'], output_quantity=r['output_quantity'],
        fee_quantity=r['fee_amount_estimate'], fee_currency=r['assumed_fee_currency_for_research'])
    return result


class GraphAndCosts(unittest.TestCase):
    def test_exact_scope_directions_hold_and_bounds(self):
        x=inputs();g=candidate_graph('BTC',catalog=x['_catalog'],rules=x['_rules'])
        legs={r['leg'] for r in g['actions']}
        self.assertIn(BTC_ETH, legs); self.assertIn(BTC_SOL, legs)
        self.assertEqual(g['actions'][0]['kind'],'HOLD')
        self.assertEqual(len(g['actions']),5)
        all_edges={a['leg'] for src in ('ETH','BTC','ADA','LINK','SOL') for a in
            candidate_graph(src,catalog=WATCH_PAIRS,rules=x['_rules'])['actions'][1:]}
        self.assertEqual(len(all_edges),14)
        self.assertIn(ETH_BTC,all_edges);self.assertIn(SOL_BTC,all_edges);self.assertIn(SOL_ETH,all_edges)
        self.assertTrue(candidate_graph('BTC',catalog=WATCH_PAIRS,rules=x['_rules'],limit=1)['truncated'])
        routes=closed_routes(catalog=WATCH_PAIRS,rules=x['_rules'])
        self.assertEqual(len(routes['routes']),10);self.assertTrue(routes['coverage_complete'])
        self.assertTrue(closed_routes(catalog=WATCH_PAIRS,rules=x['_rules'],limit=1)['truncated'])
        with self.assertRaises(ValueError):candidate_graph('USD',catalog=WATCH_PAIRS,rules=x['_rules'])

    def test_catalog_permissions_exclusions_invalid_rules_and_no_extra_pair(self):
        x=inputs();rules=x['_rules'];rules['SOL-USDC']=dict(rules['SOL-BTC'],product_id='SOL-USDC')
        for patch in ({'view_only':True},{'view_only':None},{'status':'offline'},
                      {'trading_disabled':True},{'base_increment':'0'},{'price_increment':'0'},
                      {'quote_increment':None},{'base_max_size':'.001','base_min_size':'1'}):
            changed=deepcopy(rules);changed['SOL-BTC'].update(patch)
            g=candidate_graph('BTC',catalog=tuple(rules),rules=changed)
            self.assertNotIn(BTC_SOL,[r['leg'] for r in g['actions']],patch)
        g=candidate_graph('BTC',catalog=(),rules=rules)
        self.assertEqual(len(g['actions']),1)
        g=candidate_graph('BTC',catalog=tuple(rules),rules=rules,excluded=('SOL',))
        self.assertNotIn(BTC_SOL,[r['leg'] for r in g['actions']])
        self.assertFalse(any('USDC' in str(a) for a in g['actions']))

    def test_flat_round_trip_loses_after_costs_and_canonical_fee_once(self):
        f=frame(fee='.01');r=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,BTC_ETH),frame=f)
        self.assertEqual(r['state'],'MODELED_UNVERIFIED')
        self.assertLess(r['modeled_eth'],D(1));self.assertIsNone(r['actual_profit_eth'])
        with localcontext() as ctx:
            ctx.prec=60
            for receipt in r['receipts']:
                q=receipt['gross_base_quantity'];fee=receipt['fee_rate_used']
                if receipt['side']=='SELL':
                    self.assertEqual(receipt['output_quantity'],q*D('.9985')*(1-fee))
                else:self.assertEqual(receipt['input_quantity'],q*D('1.0015')*(1+fee))
                self.assertNotIn('approx_usd_notional',receipt)
        self.assertFalse(r['execution_eligible'])

    def test_maker_uses_resting_side_no_taker_stress_and_never_a_fill(self):
        f=frame(changes={'ETH-BTC':(D(1),D('1.001'),NOW)})
        result=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,),frame=f,
                             mode='MAKER',slippage_bps=D(0))
        self.assertEqual(result['receipts'][0]['output_quantity'],D('1.001'))
        self.assertIn('MAKER_FILL_AND_EXIT_UNCERTAIN',result['limitations'])
        bad=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,),frame=f,mode='MAKER')
        self.assertIn('MAKER_HAS_NO_TAKER_SLIPPAGE',bad['reasons'])
        crossed=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,),frame=frame(),mode='MAKER',slippage_bps=D(0))
        self.assertIn('POST_ONLY_ENTRY_WOULD_CROSS',crossed['reasons'])

    def test_unknown_depth_currency_and_residuals_never_become_complete_eth(self):
        r=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,BTC_ETH),frame=frame(evidence=False))
        self.assertIsNone(r['recoverable_eth']);self.assertIn('DEPTH_UNVERIFIED',r['limitations'])
        self.assertIn('FEE_CURRENCY_UNVERIFIED',r['limitations'])
        x=inputs(fee='.01');x['_rules']['ETH-BTC']['base_increment']='.1'
        r=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,BTC_ETH),frame=Frame(**x),slippage_bps=D(0))
        self.assertGreater(r['inventory'].get('BTC',D(0)),0)
        self.assertIn('RESIDUAL_ETH_VALUE_UNKNOWN',r['limitations']);self.assertIsNone(r['recoverable_eth'])
        complete=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,BTC_ETH),frame=frame(),slippage_bps=D(0))
        self.assertEqual(complete['recoverable_eth'],D(1))

    def test_timestamp_spread_tick_depth_and_rule_rejections(self):
        for quote,reason in (((D(1),D(1),NOW-31),'QUOTE_STALE'),
                ((D(1),D(1),NOW+1),'QUOTE_FUTURE'),((D(1),D(2),NOW),'QUOTE_WIDE'),
                ((D(1),D('1.000000001'),NOW),'QUOTE_PRICE_INCREMENT_INVALID')):
            r=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,),frame=frame(changes={'ETH-BTC':quote}))
            self.assertIn(reason,r['reasons'])
        x=inputs(changes={'SOL-BTC':(D(1),D(1),NOW-13)})
        r=estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,BTC_SOL,SOL_ETH),frame=Frame(**x))
        self.assertIn('QUOTE_DECISION_SPAN_EXCEEDS_12S',r['reasons'])
        for patch in ({'base_max_size':'.5'},{'quote_max_size':'.5'},{'quote_min_size':'10'}):
            x=inputs();x['_rules']['ETH-BTC'].update(patch)
            self.assertEqual(estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,),frame=Frame(**x))['state'],'UNKNOWN')
        x=inputs();x['_depth']['ETH-BTC','SELL']['levels'][0]['size']=D('.1')
        self.assertIn('DEPTH_INSUFFICIENT',estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,),frame=Frame(**x))['reasons'])

    def test_fee_stale_future_negative_missing_and_float_inputs_fail_closed(self):
        for patch in ({'fresh':False},{'captured_at':NOW-7201},{'captured_at':NOW+1},
                      {'taker':D('-.001')},{'taker':None}):
            x=inputs();x['_tier'].update(patch)
            self.assertEqual(estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,),frame=Frame(**x))['state'],'UNKNOWN')
        self.assertEqual(estimate_path(source='ETH',quantity=1.0,path=(ETH_BTC,),frame=frame())['state'],'UNKNOWN')
        x=inputs();f=Frame(**x);x['_rules']['ETH-BTC']['base_increment']='999';x['_quotes'].clear()
        self.assertEqual(estimate_path(source='ETH',quantity=D(1),path=(ETH_BTC,),frame=f)['state'],'MODELED_UNVERIFIED')


class SharedConditionalFunds(unittest.TestCase):
    def test_only_working_slice_after_existing_carve_outs_is_usable(self):
        args=dict(balances={'ETH':D(10),'BTC':D(50)},balances_at=NOW,now=NOW,
            draft=(AllocationRow('ETH',D(2),D(3),D(4)),))
        funds=ResearchFunds.from_proposal(amount_eth=D(2),**args)
        self.assertEqual(funds.inventory(),{'ETH':D(2)})
        self.assertEqual(funds.available('BTC'),0)
        for changes in ({'amount_eth':D(3)},{'excluded':('ETH',)},{'balances_at':NOW-121}):
            with self.assertRaises(ValueError):ResearchFunds.from_proposal(**{**args,'amount_eth':D(2),**changes})

    def test_reservation_prevents_double_spending_and_uncertain_proceeds(self):
        funds=ResearchFunds(D(1));funds.reserve('a',leg=ETH_BTC,quantity=D(1),frame=frame())
        self.assertEqual(funds.available('ETH'),0);self.assertEqual(funds.available('BTC'),0)
        with self.assertRaises(ValueError):funds.reserve('b',leg=ETH_BTC,quantity=D(1),frame=frame())
        with self.assertRaises(ValueError):funds.reserve('c',leg=BTC_SOL,quantity=D(1),frame=frame())
        funds.uncertain('a')
        with self.assertRaises(ValueError):funds.no_fill('a')
        self.assertIsNone(scoreboard(funds,frame())['after_cost_recoverable_eth'])
        self.assertEqual(funds.inventory(),{'ETH':D(1)})

    def test_explicit_assumptions_only_sequential_transitions_and_replay_block(self):
        funds=ResearchFunds(D(1))
        assume(funds,'eth-btc',ETH_BTC);self.assertEqual(funds.available('BTC'),D(1))
        assume(funds,'btc-sol',BTC_SOL);self.assertEqual(funds.available('SOL'),D(1))
        assume(funds,'sol-eth',SOL_ETH);self.assertEqual(funds.available('ETH'),D(1))
        with self.assertRaises(ValueError):funds.reserve('eth-btc',leg=ETH_BTC,quantity=D(1),frame=frame())
        self.assertEqual(scoreboard(funds,frame())['verified_fills'],0)

    def test_mismatched_assumption_and_no_fill_cannot_credit_proceeds(self):
        funds=ResearchFunds(D(1));r=funds.reserve('a',leg=ETH_BTC,quantity=D(1),frame=frame())['receipts'][0]
        kwargs=dict(classification='SIMULATED_ASSUMPTION',input_quantity=r['input_quantity'],
                    output_quantity=r['output_quantity'],fee_quantity=r['fee_amount_estimate'],fee_currency='BTC')
        for patch in ({'classification':'VERIFIED_FILL'},{'output_quantity':D(10)},{'fee_currency':'ETH'}):
            with self.assertRaises(ValueError):funds.assume_fill('a',**dict(kwargs,**patch))
        self.assertEqual(funds.inventory(),{'ETH':D(1)})
        funds.no_fill('a');self.assertEqual(funds.available('ETH'),D(1))

    def test_scoreboard_shows_underwater_inventory_review_only_and_no_real_earnings(self):
        funds=ResearchFunds(D(1));assume(funds,'a',ETH_BTC);assume(funds,'b',BTC_SOL)
        value=scoreboard(funds,frame(changes={'SOL-ETH':(D('.5'),D('.5'),NOW)}),
                         real_eth=D(7),real_eth_at=NOW,alert_pct=D(15))
        # Slippage stress applies to a proposed conservative exit, not a real fill.
        self.assertLess(value['after_cost_recoverable_eth'],D('.5'))
        self.assertEqual(value['real_account_eth'],D(7));self.assertEqual(value['alert'],'REVIEW_ONLY')
        self.assertFalse(value['forced_liquidation']);self.assertEqual(funds.available('SOL'),D(1))
        self.assertLess(value['net_vs_hold_eth'],0);self.assertGreater(value['drawdown_pct'],50)
        self.assertEqual(value['realized_earnings'],'NOT_ESTABLISHED')
        stale=scoreboard(funds,frame(evidence=False),real_eth=D(7),real_eth_at=NOW-121)
        self.assertIsNone(stale['real_account_eth']);self.assertIsNone(stale['drawdown_pct'])


class ProspectiveOutcomes(unittest.TestCase):
    def freeze(self,fill_state='SIMULATED_ASSUMPTION',reference='case',study=None):
        funds=ResearchFunds(D(1));assume(funds,'seed',ETH_BTC)
        study=ForwardStudy() if study is None else study
        study.freeze(reference,funds=funds,leg=BTC_SOL,quantity=D(1),frame=frame(),
                     horizon_s=60,signal={'forecast':'UNVALIDATED'},exit_condition='AT_FIXED_HORIZON',
                     fill_state=fill_state,slippage_bps=D(0))
        self.assertEqual(funds.available('SOL'),0) # Freezing never settles a fill.
        return study

    def test_adversarial_btc_sol_outcome_and_immutable_signal(self):
        s=self.freeze();external=s.case('case');external['signal']['forecast']='CHANGED'
        self.assertEqual(s.case('case')['signal']['forecast'],'UNVALIDATED')
        s.observe('case',frame(at=NOW+30,changes={'SOL-ETH':(D('.5'),D('.5'),NOW+30)}))
        outcome=s.observe('case',frame(at=NOW+60,changes={'SOL-ETH':(D('.4'),D('.4'),NOW+60)}))
        self.assertEqual(outcome['outcome']['relative_eth'],D('-.6'))
        self.assertEqual(s.summary()['adverse'],1);self.assertEqual(s.summary()['underwater_open'],1)
        self.assertEqual(s.summary()['edge'],'NO_DEMONSTRATED_EDGE');self.assertEqual(s.summary()['decision'],'HOLD')
        self.assertEqual(s.observe('case',frame(at=NOW+61,changes={'SOL-ETH':(D(10),D(10),NOW+61)})),outcome)

    def test_non_events_partial_unknown_missed_and_unpriced_horizon_are_retained(self):
        for fill in ('NO_FILL','PARTIAL_OR_UNCERTAIN_FILL','UNVERIFIED'):
            s=self.freeze(fill);case=s.observe('case',frame(at=NOW+60))
            if fill=='NO_FILL':self.assertEqual(case['outcome']['relative_eth'],D(0))
            else:self.assertIsNone(case['outcome']['relative_eth'])
            self.assertEqual(s.summary()['registered'],1)
        s=self.freeze();self.assertEqual(s.observe('case',frame(at=NOW+91))['state'],'MISSED_HORIZON')
        s=self.freeze();case=s.observe('case',frame(at=NOW+60,evidence=False))
        self.assertEqual(case['state'],'UNKNOWN_AT_HORIZON')
        self.assertEqual(s.observe('case',frame(at=NOW+61)),case)

    def test_unchanged_and_asynchronous_forward_quotes_do_not_manufacture_edge(self):
        s=self.freeze();self.assertEqual(s.observe('case',frame(at=NOW+60))['outcome']['relative_eth'],D(0))
        s=self.freeze();f=frame(at=NOW+60,changes={'ETH-BTC':(D(1),D(1),NOW+47)})
        outcome=s.observe('case',f)
        self.assertIsNone(outcome['outcome']['relative_eth']);self.assertEqual(outcome['state'],'UNKNOWN_AT_HORIZON')

    def test_many_favorable_cases_do_not_hide_worsening_underwater_open_case(self):
        s=ForwardStudy()
        for i in range(3):
            self.freeze(reference=str(i),study=s)
            s.observe(str(i),frame(at=NOW+60,changes={'SOL-ETH':(D(2),D(2),NOW+60)}))
        self.freeze(reference='underwater',study=s)
        s.observe('underwater',frame(at=NOW+30,changes={'SOL-ETH':(D('.2'),D('.2'),NOW+30)}))
        summary=s.summary();self.assertEqual(summary['favorable'],3);self.assertEqual(summary['underwater_open'],1)
        self.assertEqual(summary['waiting'],1);self.assertEqual(summary['edge'],'NO_DEMONSTRATED_EDGE')


class RedactionAndMonitor(unittest.TestCase):
    def test_new_projection_rejects_private_fields_at_all_levels(self):
        private='PRIVATE_ACCOUNT_BALANCE_987654321'
        raw=dict(state='CONDITIONAL_RESEARCH_ONLY',inventory=private,receipts=private,
            candidates=[dict(pair='SOL-ETH',source='ETH',target='SOL',reason=private,quantity=private)])
        safe=public_summary(raw);self.assertNotIn(private,str(safe));validate_public(safe)
        for level in ('root','candidate'):
            altered=deepcopy(safe)
            (altered if level=='root' else altered['candidates'][0])['private_balance']=private
            with self.assertRaises(ValueError):validate_public(altered)

    def test_monitor_v100_v2_first_unpriced_setup_and_adaptive_whitelist(self):
        app=app_fixture();app.last_result['rows'][0]['observation_state']='NO_SETUP_UNPRICED'
        app.last_result['adaptive']=dict(state='CONDITIONAL_RESEARCH_ONLY',balance='PRIVATE',candidates=[])
        snap=capture(app,session='a'*32,sequence=1,now=NOW)
        self.assertEqual(snap['schema'],SCHEMA);self.assertEqual(SCHEMA,'coincat-monitor/v2')
        self.assertEqual(snap['version'],'CoinCat v100.0')
        self.assertEqual(snap['products'][0]['setup_state'],'NO_SETUP_UNPRICED')
        self.assertEqual(snap['products'][0]['reasons'][0],'QUOTE_WIDE')
        self.assertNotIn('PRIVATE',encode(snap).decode());self.assertIn('QUOTE_WIDE',JS)
        self.assertIn('v100',HTML);self.assertIn('No valid first setup',JS)
        with TemporaryDirectory() as folder:
            snap['adaptive']['private_balance']='PRIVATE';(Path(folder)/'latest.json').write_text(json.dumps(snap))
            with self.assertRaises(ValueError):read_snapshot(folder)


from offline_tests import gui_fixtures as fixtures
from offline_tests.test_v100_eth_growth import prepare,run_growth
from coincat_simple_diagnostics import make_report


class AdaptiveWorkspace(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def test_header_logo_position_alpha_and_fit_at_two_window_sizes(self):
        for width,height in ((1380,900),(1040,780)):
            self.root.geometry(f'{width}x{height}');self.root.update()
            logo=self.app.logo_label
            self.assertGreater(logo.winfo_rootx(),self.root.winfo_rootx()+400)
            self.assertLess(logo.winfo_rooty()+logo.winfo_height(),self.app.tabs.winfo_rooty())
            self.assertLessEqual(logo.winfo_rootx()+logo.winfo_width(),self.root.winfo_rootx()+width)
            self.assertGreaterEqual(self.app.logo.width(),400)
            self.assertTrue(self.app._logo_source.transparency_get(0,0))
            self.assertTrue(self.app.counter_label.winfo_viewable())
            self.assertLess(self.app.counter_label.winfo_rooty()+self.app.counter_label.winfo_height(),self.root.winfo_rooty()+height)
        self.assertEqual(self.app.adaptive_label.winfo_class(),'TLabel')
        self.app.tabs.select(self.app.tabs.tabs()[-1]);self.root.update()
        self.app.adaptive_label.hover_help.show();self.assertIsNotNone(self.app.adaptive_label.hover_help.window)
        self.app.adaptive_label.hover_help.hide()

    def test_scanner_summary_diagnostics_and_monitor_share_no_paper_inventory(self):
        app=self.app;_,client,scanner=prepare(self.temp.name);app.scanner=scanner;app.connected=True
        app.allocation_editor.clock=lambda:NOW;app._render_wallet();app.companions[0].set('ADA')
        app.mixer.controls['amount_eth'].set(D('.1'));app._apply_plan()
        before=fixtures.ledger_dump(app.ledger)
        result=run_growth(scanner,client);app.last_result=result;app._render(result);self.root.update()
        safe=public_summary(result['adaptive'])
        self.assertEqual(safe['paper_positions'],0);self.assertEqual(safe['decision'],'HOLD')
        self.assertIn('NO DEMONSTRATED EDGE',app.adaptive_text.get())
        report=make_report(app,now=NOW)
        for text in ('CoinCat v100.0','COMPLETE (8/8)','adaptive_eth','NO_DEMONSTRATED_EDGE','BLOCKED_UNCONDITIONALLY'):
            self.assertIn(text,report)
        snapshot=capture(app,session='a'*32,sequence=1,now=NOW)
        self.assertEqual(snapshot['adaptive'],safe)
        self.assertNotIn('inventory',encode(snapshot).decode())
        self.assertEqual(fixtures.ledger_dump(app.ledger),before)
        self.assertFalse(hasattr(scanner,'paper_funds'))

    def test_stop_rejects_queued_new_summary_and_monitor_retains_stopped_state(self):
        app=self.app;_,client,scanner=prepare(self.temp.name);app.scanner=scanner;app.connected=True
        result=run_growth(scanner,client);generation=app.generation
        app._stop();app.jobs.put(('scan',generation,result,None));app._poll()
        self.assertIsNone(app.last_result)
        snap=capture(app,session='a'*32,sequence=1,now=NOW)
        self.assertFalse(snap['health']['running']);self.assertEqual(snap['adaptive']['state'],'UNOBSERVED')

    def test_utf8_labels_and_snowball_compatibility_survive_current_text_cleanup(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/'app/coincat_app.py').read_text(encoding='utf-8')
        self.assertIn('BTC → SOL',app);self.assertIn('HOLD · NO DEMONSTRATED EDGE',app)
        self.assertIn('ΔETH',app)
        for path in (root/'app').glob('*.py'):
            text=path.read_text(encoding='utf-8')
            self.assertNotIn('\ufffd',text,path.name)
            self.assertNotIn('â†',text,path.name)
        compatibility=(root/'app/coincat_v80_immediate.py').read_text(encoding='utf-8')
        self.assertIn("snowball_state='IMMEDIATE_ESTIMATE'",compatibility)
        self.assertIn('snowball_immediate_usd',compatibility)
