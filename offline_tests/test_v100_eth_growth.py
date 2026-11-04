"""v100 direct-ETH economics, uncertain fills, read-only integration and real Tk."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from unittest.mock import Mock,patch
import threading
import time
import unittest

from coincat_eth_maker import (MakerConfig,MakerStudy,select_markets,available_companions,
    model_market,evaluate_completion,post_only_eligible,public_summary)
from coincat_working_allocation import AllocationRow
from coincat_scanner import Scanner
from coincat_simple_diagnostics import make_report
from offline_tests import gui_fixtures as fixtures
from offline_tests.test_native_receipts import NOW

TIER=dict(fresh=True,maker=D('.005'),taker=D('.009'),age_s=0,
          source='AUTHENTICATED_SPOT_TRANSACTION_SUMMARY',state='ACCOUNT_TIER_VERIFIED')


def inputs(inverse=False):
    pair='ETH-ADA' if inverse else 'ADA-ETH'
    rules={pair:dict(product_id=pair,product_type='SPOT',status='online',view_only=False,
        base_increment='.00000001' if inverse else '.01',quote_increment='.00000001',
        price_increment='.00000001' if not inverse else '.01',
        base_min_size='.00000001',quote_min_size='.00000001')}
    quote=(D('4999'),D('5000'),NOW) if inverse else (D('.0002'),D('.0002001'),NOW)
    m=select_markets([pair],rules,('ADA',))['selected'][0]
    return m,rules,quote


def modeled(**changes):
    market,rules,quote=inputs()
    args=dict(market=market,config=MakerConfig(('ADA',),D('.1')),rules=rules,
              raw_quote=quote,tier=deepcopy(TIER),now=NOW)
    args.update(changes);return model_market(**args)


class DirectMarketSelection(unittest.TestCase):
    def test_explicit_four_companion_ceiling_and_no_auto_replacement(self):
        m,r,q=inputs();r['ADA-USD']=dict(r[m['pair']],product_id='ADA-USD')
        selection=select_markets(list(r),r,('BTC','ADA','SOL'))
        self.assertEqual([x['pair'] for x in selection['selected']],['ADA-ETH'])
        self.assertEqual(set(selection['rejects']),{'BTC','SOL'})
        MakerConfig(('BTC','ADA','SOL','LINK')).validate()
        with self.assertRaises(ValueError):select_markets(list(r),r,('BTC','ADA','SOL','LINK','XRP'))
        for bad in ('ETH','USD','USDC','private-identifier'):
            with self.assertRaises(ValueError):select_markets(list(r),r,(bad,))
        with self.assertRaises(ValueError):select_markets(list(r),r,('ADA','ADA'))

    def test_missing_permissions_rules_status_or_actual_listing_never_qualify(self):
        m,r,q=inputs();pair=m['pair']
        for changes in ({'view_only':True},{'view_only':None},{'status':'offline'},
                        {'base_increment':'0'},{'quote_increment':None},{'product_id':'FAKE-ETH'},
                        {'trading_disabled':True},{'limit_only':True},{'post_only':True},
                        {'product_type':'FUTURE'},{'base_currency_id':'BTC'}):
            changed={pair:dict(r[pair],**changes)}
            self.assertFalse(select_markets([pair],changed,('ADA',))['selected'],changes)
        self.assertFalse(select_markets([],r,('ADA',))['selected'])
        self.assertEqual(available_companions([pair],r),['ADA'])
        self.assertEqual(available_companions([pair],r,('ETH',)),[])

    def test_real_inverse_orientation_and_stablecoin_bridge_exclusion(self):
        m,r,q=inputs(True)
        self.assertEqual((m['entry_side'],m['exit_side']),('SELL','BUY'))
        self.assertEqual(select_markets(['ADA-USD','ETH-USD'],r,('ADA',))['state'],'NO_QUALIFIED_EVIDENCE')
        self.assertFalse(select_markets(list(r),r,('ADA',),('ADA',))['selected'])


class MakerEconomics(unittest.TestCase):
    def test_immediate_taker_benchmark_negative_maker_target_not_profit(self):
        row=modeled();self.assertEqual(row['state'],'RESEARCH_ONLY')
        b=row['benchmark'];h=row['hypothesis']
        self.assertLess(b['net_eth_subtotal'],0)
        self.assertGreater(h['required_move_pct'],1)
        self.assertGreaterEqual(h['scenario']['net_pct_subtotal'],D('.25'))
        self.assertEqual(h['scenario']['initial_eth'],D('.1'))
        self.assertEqual(h['scenario']['actual_profit_eth'],None)
        self.assertEqual(h['scenario_bounds']['no_fill_eth'],D('.1'))
        self.assertIsNone(h['scenario_bounds']['partial_completion_eth'])
        self.assertEqual(h['fill_state'],'UNVERIFIED');self.assertIsNone(h['exit_at'])
        self.assertFalse(row['execution_eligible'])

    def test_fees_once_and_no_taker_slippage_applied_to_maker(self):
        row=modeled();h=row['hypothesis'];first,second=h['scenario']['receipts']
        self.assertEqual(first['input_quantity'],first['gross_base_quantity']*h['entry_price']*D('1.005'))
        self.assertEqual(second['output_quantity'],second['gross_base_quantity']*h['exit_price']*D('.995'))
        self.assertEqual(h['scenario']['final_eth_subtotal'],D('.1')-first['input_quantity']+second['output_quantity'])
        self.assertTrue(all(r['modeled_slippage_fraction']==0 for r in h['scenario']['receipts']))
        changed=modeled(config=replace(MakerConfig(('ADA',),D('.1')),taker_slippage_bps=D(50)))
        self.assertEqual(h,changed['hypothesis'])
        self.assertGreater(row['benchmark']['net_eth_subtotal'],changed['benchmark']['net_eth_subtotal'])

    def test_maker_entry_crossing_and_tick_validation(self):
        m,r,q=inputs()
        self.assertFalse(post_only_eligible('BUY',q[1],q,m['tick']))
        self.assertFalse(post_only_eligible('SELL',q[0],q,m['tick']))
        self.assertFalse(post_only_eligible('BUY',D('.000199999'),q,m['tick']))
        row=modeled(raw_quote=(q[0],q[0],NOW))
        self.assertIn('POST_ONLY_ENTRY_WOULD_CROSS',row['blockers'])
        self.assertIsNotNone(row['benchmark']);self.assertIsNone(row['hypothesis'])

    def test_inverse_eth_base_sizing_and_eth_per_coin(self):
        m,r,q=inputs(True)
        row=modeled(market=m,rules=r,raw_quote=q)
        self.assertIsNotNone(row['hypothesis'],row['blockers'])
        self.assertAlmostEqual(row['eth_per_coin'],D(1)/D('4999.5'))
        h=row['hypothesis'];self.assertLess(h['exit_price'],h['entry_price'])
        self.assertEqual(h['scenario']['receipts'][0]['input_asset'],'ETH')
        self.assertEqual(h['scenario']['receipts'][1]['output_asset'],'ETH')
        self.assertGreaterEqual(h['scenario']['net_pct_subtotal'],D('.25'))

    def test_native_dust_preserved_and_never_called_complete_eth(self):
        m,r,q=inputs(True);row=modeled(market=m,rules=r,raw_quote=q)
        scenario=row['hypothesis']['scenario']
        self.assertTrue(scenario['native_dust']);self.assertIsNone(scenario['complete_net_eth'])
        self.assertIn('ADA',scenario['native_dust'])
        self.assertNotIn('approx_usd_notional',str(scenario))
        self.assertEqual(scenario['fee_currency'],'UNVERIFIED_QUOTE_DEBIT_SCENARIO')

    def test_stale_wide_future_missing_and_nonfinite_quotes_are_unpriced(self):
        for quote in (None,(D('.0002'),D('.0002001'),NOW-31),
                      (D('.0002'),D('.0002001'),NOW+1),(D('.0002'),D('.0003'),NOW),
                      (D('NaN'),D('.0002001'),NOW)):
            row=modeled(raw_quote=quote)
            self.assertEqual(row['state'],'UNPRICED');self.assertIsNone(row['benchmark'])
            self.assertIsNone(row['hypothesis'])

    def test_missing_stale_unsupported_fee_tiers_have_no_fixed_fee_fallback(self):
        for tier in ({},{'fresh':False},dict(TIER,maker=None),dict(TIER,maker=D('-.001')),
                     dict(TIER,taker=D('.05'))):
            row=modeled(tier=tier);self.assertIsNone(row['hypothesis']);self.assertIsNone(row['benchmark'])
        zero=modeled(tier=dict(TIER,maker=D(0),taker=D(0)))
        self.assertIsNotNone(zero['hypothesis'])
        self.assertIn('FEE_CURRENCY_UNVERIFIED',zero['hypothesis']['limits'])

    def test_each_leg_min_max_and_precision_block_without_size_fitting(self):
        m,r,q=inputs()
        for field,value in (('base_min_size','100000'),('quote_min_size','1'),
                             ('base_max_size','1'),('quote_max_size','.001')):
            rules={m['pair']:dict(r[m['pair']],**{field:value})}
            row=modeled(rules=rules);self.assertIsNone(row['hypothesis'])
        rules={m['pair']:dict(r[m['pair']],quote_max_size='.1')}
        row=modeled(rules=rules)  # Entry fits but the target exit exceeds quote max.
        self.assertIn('MAKER_EXIT_PRODUCT_SIZE_BLOCK',row['blockers'])
        self.assertIsNone(modeled(config=MakerConfig(('ADA',),D('0')))['hypothesis'])

    def completion(self,**changes):
        m,r,q=inputs();h=modeled()['hypothesis']
        exit_book=(h['exit_price']-D('.00000002'),h['exit_price']-D('.00000001'),NOW+3600)
        args=dict(market=m,amount=D('.1'),entry_price=h['entry_price'],exit_price=h['exit_price'],
            entry_quote=q,exit_quote=exit_book,entry_at=NOW,exit_at=NOW+3600,
            entry_fee=D('.005'),exit_fee=D('.005'),rules=r)
        args.update(changes);return evaluate_completion(**args)

    def test_two_timepoints_independently_qualified_not_forced_into_12_seconds(self):
        result=self.completion(fill_state='HYPOTHETICAL_FULL_FILL')
        self.assertIsNotNone(result['scenario']);self.assertIsNone(result['actual_profit_eth'])
        self.assertFalse(result['execution_eligible'])
        result=self.completion(exit_quote=(D('.0002'),D('.0002001'),NOW))
        self.assertEqual(result['fill_state'],'UNPRICED')

    def test_no_fill_partial_unknown_cancelled_have_no_credited_eth_return(self):
        for status in ('NO_FILL','PARTIAL_OR_UNCERTAIN_FILL','UNVERIFIED','CANCELLED_OR_EXPIRED'):
            result=self.completion(fill_state=status)
            self.assertIsNone(result['scenario']);self.assertIsNone(result['actual_profit_eth'])
            if status=='NO_FILL':self.assertEqual(result['remaining_eth'],D('.1'))
        self.assertEqual(self.completion(exit_at=NOW-1)['fill_state'],'UNPRICED')

    def test_later_marketable_limit_is_rejected_as_new_post_only_decision(self):
        h=modeled()['hypothesis']
        result=self.completion(exit_quote=(h['exit_price'],h['exit_price']+D('.00000001'),NOW+3600))
        self.assertEqual(result['reason'],'POST_ONLY_WOULD_CROSS')


class UncertainObservations(unittest.TestCase):
    def test_price_touch_then_target_cross_is_still_uncertain_not_a_fill(self):
        study=MakerStudy();row=modeled();study.observe([row],key='a',now=NOW)
        entry=row['hypothesis']['entry_price'];target=row['hypothesis']['exit_price']
        touched=modeled(raw_quote=(entry-D('.00000001'),entry,NOW+10),now=NOW+10)
        study.observe([touched],key='a',now=NOW+10)
        crossed=modeled(raw_quote=(target,target+D('.00000001'),NOW+40),now=NOW+40)
        study.observe([crossed],key='a',now=NOW+40)
        h=crossed['hypothesis']
        self.assertEqual(h['entry_price'],entry);self.assertEqual(h['entry_at'],NOW)
        self.assertEqual(h['fill_state'],'PARTIAL_OR_UNCERTAIN_FILL');self.assertIsNone(h['exit_at'])
        self.assertEqual(h['target_touched_at'],NOW+40)
        self.assertEqual(study.counts['target_touches_uncertain'],1)
        public=public_summary({'rows':[crossed],'study_counts':study.counts})
        self.assertEqual(public['hypothetical_full_fills'],0);self.assertEqual(public['verified_fills'],0)

    def test_declining_relative_price_no_touch_adverse_exposure_waiting(self):
        study=MakerStudy();study.observe([modeled()],key='a',now=NOW)
        row=modeled(raw_quote=(D('.00019'),D('.0001901'),NOW+10),now=NOW+10)
        study.observe([row],key='a',now=NOW+10)
        self.assertLess(row['hypothesis']['adverse_move_pct'],0)
        self.assertEqual(row['hypothesis']['waiting_s'],10)
        self.assertEqual(row['hypothesis']['scenario']['actual_profit_eth'],None)

    def test_fee_change_allocation_change_gap_and_expiry_invalidate_old_setups(self):
        study=MakerStudy();study.observe([modeled()],key='a',now=NOW)
        changed=modeled(tier=dict(TIER,maker=D('.006')),now=NOW+1,
                        raw_quote=(D('.0002'),D('.0002001'),NOW+1))
        study.observe([changed],key='a',now=NOW+1)
        self.assertEqual(study.counts['fee_changes'],1)
        self.assertEqual(changed['hypothesis']['maker_rate'],D('.006'))
        study.observe([modeled()],key='changed_allocation',now=NOW)
        self.assertEqual(study.counts['invalidated'],2)
        self.assertEqual(study.invalidations['ACCOUNT_FEE_RATE_CHANGED'],1)
        bad=modeled(raw_quote=None);study.observe([bad],key='changed_allocation',now=NOW+1)
        self.assertEqual(bad['observation_state'],'SETUP_ACTIVE_UNPRICED')
        self.assertEqual(len(study.active),1)
        study.observe([modeled()],key='b',now=NOW)
        expired=modeled(raw_quote=(D('.0002'),D('.0002001'),NOW+86400),now=NOW+86400)
        study.observe([expired],key='b',now=NOW+86400)
        self.assertEqual(expired['fill_state'],'CANCELLED_OR_EXPIRED')
        self.assertEqual(study.active,{})


class GrowthClient(fixtures.FakeClient):
    def __init__(self):
        super().__init__();m,self.rules,q=inputs();self.q={m['pair']:q}
    def get_accounts(self,**kwargs):
        self.calls.append('accounts')
        return {'accounts':[{'currency':'ETH','available_balance':{'value':'2'},'hold':{'value':'0'}}],'has_next':False}


def prepare(folder):
    ledger,_,s=fixtures.setup(folder);client=GrowthClient()
    s=Scanner(ledger,client,s.fees,s.market_store);s.refresh(now=NOW)
    return ledger,client,s


def run_growth(s,client,**changes):
    args=dict(now=NOW,collect=fixtures.collector(client),allocation_draft=(AllocationRow('ETH',D(2)),))
    args.update(changes);return s.scan_growth(MakerConfig(('ADA',),D('.1')),**args)


class ReadOnlyGrowth(unittest.TestCase):
    def test_three_watch_books_and_12_second_per_decision_span_stay_bounded(self):
        from coincat_v701_transport import QuoteSnapshot
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder)
            template=deepcopy(s.rules['ADA-ETH'])
            native=fixtures.FakeClient();s.rules['ETH-BTC']=dict(native.rules['ETH-BTC'],view_only=False)
            s.catalog.append('ETH-BTC');c.q['ETH-BTC']=native.q['ETH-BTC']
            for asset in ('SOL',):
                pair=asset+'-ETH';s.rules[pair]=dict(template,product_id=pair)
                s.catalog.append(pair);c.q[pair]=c.q['ADA-ETH']
            config=MakerConfig(('ADA','BTC','SOL'),D('.1'))
            result=s.scan_growth(config,now=NOW,collect=fixtures.collector(c),
                                 allocation_draft=(AllocationRow('ETH',D(2)),))
            self.assertEqual(len(result['rows']),3)
            self.assertEqual(result['quote_scheduling']['research_books'],3)
            def skew(pairs,**kwargs):
                return {p:QuoteSnapshot(p,*c.q[p][:2],NOW-(13 if i==0 else 0),NOW,1)
                        for i,p in enumerate(pairs)}, {},1
            result=s.scan_growth(config,now=NOW,collect=skew,allocation_draft=(AllocationRow('ETH',D(2)),))
            self.assertTrue(all(r['observation_state']=='SETUP_ACTIVE_UNPRICED' for r in result['rows']))
            self.assertTrue(all(r['benchmark'] is None and not r['current_estimate_available'] for r in result['rows']))
            self.assertTrue(all('QUOTE_DECISION_SPAN_EXCEEDS_12S' in r['blockers'] for r in result['rows']))

    def test_future_dated_and_expired_account_fee_cache_is_unverified(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder)
            self.assertFalse(s.fees.latest_tier(now=NOW-1)['fresh'])
            self.assertFalse(s.fees.latest_tier(now=NOW+7201)['fresh'])
            self.assertEqual(s.fees.latest_tier(now=NOW)['captured_at'],NOW)

    def test_only_selected_watch_books_no_old_experiments_or_financial_writes(self):
        with TemporaryDirectory() as folder:
            ledger,c,s=prepare(folder);before=fixtures.ledger_dump(ledger)
            collect=Mock(side_effect=fixtures.collector(c))
            result=run_growth(s,c,collect=collect)
            self.assertEqual(collect.call_args.args[0],('ADA-ETH',))
            self.assertEqual(result['quote_scheduling']['research_books'],1)
            self.assertEqual(before,fixtures.ledger_dump(ledger));self.assertFalse(hasattr(s,'lab'))
            self.assertEqual(result['orders_submitted'],0);self.assertFalse(result['live_order_permission'])
            frozen=deepcopy(result);s.rules.clear();s.balances.clear();c.q.clear()
            self.assertEqual(result,frozen)

    def test_no_balance_fallback_excluded_or_protected_funds(self):
        with TemporaryDirectory() as folder:
            ledger,c,s=prepare(folder)
            for draft in ((),(AllocationRow('ETH',D(0),protected=D(2)),),
                          (AllocationRow('ETH',D('.01'),manual=D('1.99')),)):
                r=run_growth(s,c,allocation_draft=draft)
                self.assertEqual(r['state'],'NO_QUALIFIED_EVIDENCE')
                self.assertTrue(all(row['hypothesis'] is None for row in r['rows']))
            ledger.approve_all({'ETH':'2'});ledger.set_asset_enabled('ETH',False)
            self.assertEqual(run_growth(s,c)['rows'],[])

    def test_disconnect_cannot_reuse_previous_book(self):
        with TemporaryDirectory() as folder:
            from coincat_recovery import ReadFailure
            _,c,s=prepare(folder);previous=run_growth(s,c)
            with self.assertRaises(ReadFailure) as error:
                run_growth(s,c,collect=lambda *a,**k:({}, {'ConnectionError':1},1))
            self.assertEqual(error.exception.detail['category'],'CONNECTION_ERROR')
            self.assertIs(s.last_result,previous);self.assertEqual(s.sequence,1)
            s.pause_observation('CONNECTION_ERROR',now=NOW)
            self.assertTrue(s.maker_study.active['ADA-ETH']['_paused'])

    def test_stop_before_during_collection_or_evaluation_commits_no_study(self):
        with TemporaryDirectory() as folder:
            _,c,s=prepare(folder);cancel=threading.Event();cancel.set();collect=Mock()
            self.assertEqual(run_growth(s,c,cancel=cancel,collect=collect)['state'],'CANCELLED')
            collect.assert_not_called();cancel.clear()
            def stop(pairs,**kw):cancel.set();return fixtures.collector(c)(pairs,**kw)
            self.assertEqual(run_growth(s,c,cancel=cancel,collect=stop)['state'],'CANCELLED');cancel.clear()
            original=MakerStudy.observe
            def stop_eval(study,*args,**kwargs):
                r=original(study,*args,**kwargs);cancel.set();return r
            with patch.object(MakerStudy,'observe',stop_eval):
                self.assertEqual(run_growth(s,c,cancel=cancel)['state'],'CANCELLED')
            self.assertEqual(s.sequence,0);self.assertIsNone(s.last_result)
            self.assertEqual(s.maker_study.counts,{})

    def test_quantity_free_diagnostics_match_v100_no_legacy_claims(self):
        with TemporaryDirectory() as folder:
            ledger,c,s=prepare(folder);result=run_growth(s,c)
            sentinel='0.1234567890987654321'
            result['rows'][0]['hypothesis']['scenario']['initial_eth']=D(sentinel)
            from types import SimpleNamespace
            app=SimpleNamespace(scanner=s,last_result=result,ledger=ledger,connected=True,
                running=False,busy=False,last_error=None)
            report=make_report(app,now=NOW)
            for text in ('CoinCat v1.03beta','COMPLETE (8/8)','ETH MAKER RESEARCH','NOT_ESTABLISHED','BLOCK_ON'):
                self.assertIn(text,report)
            for text in (sentinel,str(ledger.path),"'receipts':",'91.0','best_advantage_usd'):
                self.assertNotIn(text,report)


class GrowthGUI(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def prepare(self):
        _,c,s=prepare(self.temp.name);self.app.scanner=s;self.app.connected=True
        self.app.allocation_editor.clock=lambda:NOW
        self.app._render_wallet()
        self.app.companions[0].set('ADA')
        self.app.mixer.controls['amount_eth'].set(D('.1'))
        self.app._apply_plan();return c,s

    def test_large_transparent_logo_v100_four_tabs_six_faders_and_hover_coverage(self):
        self.assertIn('v1.03beta',self.root.title());self.assertIn('LIVE block ON',self.root.title())
        self.assertGreaterEqual(self.app.logo.width(),400)
        self.assertLessEqual(self.app.logo.width(),750)
        self.assertTrue(self.app._logo_source.transparency_get(0,0))
        self.assertEqual(len(self.app.tabs.tabs()),4)
        self.assertEqual(len(self.app.mixer.controls),6)
        self.assertIsNone(self.app.applied_config)
        widgets=[]
        def visit(parent):
            for w in parent.winfo_children():
                if w.winfo_class() in ('TButton','TEntry','TScale','TCombobox','Treeview','TLabel','TCheckbutton'):
                    widgets.append(w)
                visit(w)
        visit(self.root)
        self.assertTrue(widgets);self.assertTrue(all(hasattr(w,'hover_help') for w in widgets))
        self.root.update();self.assertLessEqual(self.app.mixer.winfo_reqwidth(),self.root.winfo_width())

    def test_exact_manual_entry_keyboard_reset_invalid_values_and_hover_cleanup(self):
        fader=self.app.mixer.controls['amount_eth']
        fader.text.set('.123456789');fader._entered();self.assertEqual(fader.value,D('.123456789'))
        fader._step(1);self.assertEqual(fader.value,D('.124456789'))
        fader.text.set('NaN');fader._entered();self.assertEqual(fader.value,D('.124456789'))
        self.assertIn('Invalid',fader.error.get());fader.set(D(0))
        tip=fader.entry.hover_help;tip.show();self.assertIsNotNone(tip.window)
        tip.hide();self.assertIsNone(tip.window);tip.schedule();self.app._close()
        self.root.tk.call('update','idletasks')

    def test_render_details_diagnostics_stop_and_stale_queue(self):
        c,s=self.prepare();result=run_growth(s,c)
        self.app.last_result=result;self.app._render(result);self.root.update()
        self.assertEqual(len(self.app.growth_tree.get_children()),1)
        help_text=self.app._row_help()
        for text in ('non-ETH dust','HOLD ETH','No-fill','Partial/unknown'):
            self.assertIn(text,help_text)
        self.assertIn('Actual profit: not established',self.app.evidence_text.get())
        self.app._stop();self.app.jobs.put(('scan',self.app.generation-1,{},None));self.app._poll()
        self.assertIs(self.app.last_result,result)
        self.assertEqual(len(self.app.growth_tree.get_children()),1)
        self.assertIn('COMPLETE (8/8)',make_report(self.app,now=NOW))

    def test_manual_changes_and_unapplied_allocation_edits_invalidate_pending_results(self):
        c,s=self.prepare();old_generation=self.app.generation
        self.assertIsNotNone(self.app.applied_config)
        self.app.mixer.controls['target_pct'].text.set('.5')
        self.assertIsNone(self.app.applied_config);self.assertGreater(self.app.generation,old_generation)
        self.app._apply_plan();self.assertIsNotNone(self.app.applied_config)
        editor=self.app.allocation_editor;editor.tree.selection_set('ETH');editor._select()
        editor.fields['protected'].set('1')
        self.assertIsNone(self.app.applied_config);self.app._apply_plan()
        self.assertIn('allocation edits',self.app.status.get())

    def test_no_auto_companion_selection_and_no_unapplied_start(self):
        self.app._start();self.assertFalse(self.app.running)
        c,s=self.prepare();self.app._invalidate();self.app._start();self.assertFalse(self.app.running)
        self.app.companions[0].set('');self.app._apply_plan();self.assertIsNone(self.app.applied_config)
        self.assertIn('Choose at least one',self.app.status.get())

    def test_async_start_and_stop_has_no_old_experiment_or_record_mutation(self):
        c,s=self.prepare();before=fixtures.ledger_dump(self.app.ledger)
        with patch('coincat_scanner.time.time',return_value=NOW),patch('coincat_scanner.SCOUT.collect',side_effect=fixtures.collector(c)):
            self.app._start();deadline=time.monotonic()+5
            while self.app.last_result is None and time.monotonic()<deadline:
                self.root.update();time.sleep(.005)
        self.assertIsNotNone(self.app.last_result);self.app._stop()
        self.assertEqual(self.app.last_result['mode'],'ETH_GROWTH')
        self.assertEqual(before,fixtures.ledger_dump(self.app.ledger))
        self.assertFalse(hasattr(s,'lab'))
