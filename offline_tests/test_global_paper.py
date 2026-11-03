"""v1.02 global cap/USD-floor gates with no fabricated profit or account funds."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from contextlib import closing
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from coincat_adaptive_eth import Frame
from coincat_auto_paper import AutoPaper,validate_public
from coincat_global_paper import (GlobalSettings,GLOBAL_POLICY,USD_PAIR,USD_SOURCE,revision,validate_history,
    usd_reference,qualification,global_candidates,source_budget,completed_reports)
from coincat_paper_engine import PaperBlocked
from coincat_paper_policy import paper_frame,DIRECTIONS
from coincat_paper_venue import event
from coincat_monitor import capture,validate
from coincat_v701_transport import QuoteSnapshot,QuoteErrors
from offline_tests import test_auto_paper as fixtures
from offline_tests import gui_fixtures
from offline_tests import test_v100_market_workspace as markets
from coincat_eth_maker import MakerConfig
from coincat_working_allocation import AllocationRow

NOW=fixtures.NOW


def evidence_frame(at=NOW+10,*,evidence=True,changes=None):
    f=fixtures.frame(at,changes=dict({'SOL-ETH':(D('1.199'),D('1.2'),at)},**(changes or {})))
    depth={};units={}
    if evidence:
        for pair,book in f._quotes.items():
            for side,index in (('BUY',1),('SELL',0)):
                depth[pair,side]=dict(pair=pair,side=side,observed_at=book[2],levels=[dict(price=book[index],size=D(100))])
                units[pair,side]=dict(currency=pair.split('-')[1],verified=True,observed_at=book[2])
    return Frame(at,f._catalog,f._rules,f._quotes,f._tier,f._excluded,_depth=depth,_fee_units=units)


def usd(at=NOW+10,**changes):
    return dict(dict(pair=USD_PAIR,source=USD_SOURCE,bid=D(1000),ask=D(1001),observed_at=at),**changes)


class GlobalPolicy(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.manager=AutoPaper(Path(self.temp.name)/'paper')
        self.manager.create(fixtures.config(),at=NOW,funding=fixtures.funding())

    def funded(self):
        fixtures.AutoIntegration.fund_asset(self.manager,'SOL')
        return self.manager

    def apply(self,**changes):
        return self.manager.apply_global(GlobalSettings(**changes),at=NOW+3)

    def rows(self,*,at=NOW+10,reference=True,evidence=True):
        f=evidence_frame(at,evidence=evidence);planning=paper_frame(f,self.manager.config,planning=True)
        settings=GlobalSettings(**self.manager.engine.private_state()['auto']['global_history'][-1]['settings'])
        return global_candidates(self.manager.engine,planning,self.manager.config,settings,usd(at) if reference else None)

    def test_defaults_and_whole_cent_profit_floor_and_source_cap_bounds(self):
        settings=GlobalSettings().checked()
        self.assertEqual(settings.min_net_usd,D('.01'));self.assertEqual(settings.source_pct,50)
        self.assertEqual(settings.initial_pct,50);self.assertEqual(settings.review_s,30);self.assertEqual(settings.reconsider_s,120)
        for change in (dict(min_net_usd=D('.009')),dict(min_net_usd=D('.015')),dict(min_net_usd=True),
                dict(source_pct=D('50.01')),dict(initial_pct=D(51)),dict(review_s=True),dict(reconsider_s=0)):
            with self.subTest(change=change),self.assertRaises(ValueError):replace(settings,**change).checked()

    def test_initial_slice_is_fifty_percent_of_working_once_without_double_halving(self):
        m=AutoPaper(Path(self.temp.name)/'initial')
        m.create(fixtures.config(amount_eth=D('.5')),at=NOW,funding=fixtures.funding(),global_settings=GlobalSettings())
        state=m.engine.private_state();self.assertEqual(state['wallet'],{'ETH':D('.5')})
        f=paper_frame(evidence_frame(),m.config,planning=True)
        rows=global_candidates(m.engine,f,m.config,GlobalSettings(),usd(),kickoff=True)
        self.assertEqual(rows['ETH_BTC']['source_budget'],D('.5'))
        self.assertTrue(state['auto']['global_initial_slice'])
        bad=AutoPaper(Path(self.temp.name)/'too_large')
        with self.assertRaises(PaperBlocked):
            bad.create(fixtures.config(amount_eth=D('.51')),at=NOW,funding=fixtures.funding(),global_settings=GlobalSettings())

    def test_cap_is_percentage_of_available_then_native_cap_not_half_of_the_cap(self):
        state=self.manager.engine.private_state();state['limits']['source_caps']['SOL']=D(3)
        self.assertEqual(source_budget(state,D(10),dict(source='SOL'),GlobalSettings()),3)
        self.assertEqual(source_budget(state,D(4),dict(source='SOL'),GlobalSettings()),2)
        self.assertEqual(source_budget(state,D(4),dict(source='SOL'),GlobalSettings(),ceiling=D('.4')),D('.4'))

    def test_all_fourteen_directions_share_one_global_target_and_half_source(self):
        self.funded();self.apply();rows=self.rows()
        self.assertEqual(set(rows),{v['id'] for v in DIRECTIONS})
        state=self.manager.engine.private_state()
        self.assertEqual(rows['SOL_ETH']['source_budget'],state['wallet']['SOL']/2)
        for row in rows.values():
            if row.get('qualification'):self.assertEqual(row['qualification']['minimum_usd'],D('.01'))

    def test_known_native_eth_return_includes_entry_cost_and_exit_fee_once(self):
        self.funded();self.apply();row=self.rows()['SOL_ETH'];proof=row['qualification']
        self.assertEqual(row['state'],'CANDIDATE');self.assertEqual(proof['state'],'CONDITIONAL_QUALIFIED')
        self.assertEqual(proof['original_eth'],D('.25125'))
        self.assertEqual(proof['return_eth'],D('.294'))
        self.assertEqual(proof['net_eth'],D('.04275'));self.assertEqual(proof['net_usd'],D('42.75'))
        self.assertIsNone(proof['actual_profit_usd'])

    def test_higher_target_reprices_targets_and_changes_qualification_without_growing_quantity(self):
        self.funded();self.apply();before=self.rows()['SOL_ETH']
        self.manager.apply_global(GlobalSettings(min_net_usd=D(50)),at=NOW+4)
        after=self.rows()['SOL_ETH']
        self.assertEqual(after['state'],'HOLD');self.assertEqual(before['source_budget'],after['source_budget'])
        self.assertGreater(after['target_exit']['limit_price'],before['target_exit']['limit_price'])
        self.assertEqual(len(self.manager.engine.private_state()['auto']['global_history']),2)

    def test_missing_fee_units_or_depth_or_usd_reference_is_unknown_not_a_cent_profit(self):
        self.funded();self.apply()
        for row in (self.rows(reference=False)['SOL_ETH'],self.rows(evidence=False)['SOL_ETH']):
            self.assertEqual(row['state'],'UNKNOWN');self.assertIsNone(row['qualification']['net_usd'])
        f=evidence_frame();f._depth.clear()
        row=global_candidates(self.manager.engine,paper_frame(f,self.manager.config,planning=True),self.manager.config,
            GlobalSettings(),usd())['SOL_ETH']
        self.assertEqual(row['state'],'UNKNOWN');self.assertEqual(row['reason'],'DEPTH_UNVERIFIED')

    def test_reference_requires_approved_pair_source_age_spread_and_decision_span(self):
        f=evidence_frame()
        for ref in (usd(pair='ETH-USDC'),usd(source='MANUAL'),usd(observed_at=NOW-21),usd(observed_at=NOW+11),
                usd(bid=D(990)),usd(bid=0),usd(observed_at=True)):
            with self.subTest(ref=ref),self.assertRaises((ValueError,TypeError)):usd_reference(f,ref)
        with self.assertRaises(ValueError):usd_reference(f,usd(),stamps=(NOW-3,))

    def test_apply_is_versioned_idempotent_and_does_not_mutate_orders_wallet_or_limits(self):
        self.funded();before=self.manager.engine.private_state();self.assertEqual(self.apply(),1)
        after=self.manager.engine.private_state()
        for key in ('wallet','orders','limits','fills'):self.assertEqual(before[key],after[key])
        rev=self.manager.engine._revision;self.assertEqual(self.apply(),1);self.assertEqual(self.manager.engine._revision,rev)
        validate_history(after['auto']['global_history'])

    def test_history_and_old_order_version_cannot_be_rewritten_through_cache(self):
        self.funded();self.apply();context=self.manager.engine.private_state()['auto']
        context['global_history']=[]
        with self.assertRaises(ValueError):self.manager.engine.checkpoint_context(context)
        context=self.manager.engine.private_state()['auto'];context['global_history'][0]['settings']['min_net_usd']=D(50)
        with self.assertRaises(ValueError):self.manager.engine.checkpoint_context(context)

    def test_revision_exhaustion_retains_last_applied_policy(self):
        with patch('coincat_global_paper.MAX_REVISIONS',2):
            self.apply();self.manager.apply_global(GlobalSettings(min_net_usd=D('.1')),at=NOW+4)
            before=self.manager.engine.private_state()
            with self.assertRaises(ValueError):self.manager.apply_global(GlobalSettings(min_net_usd=D(1)),at=NOW+5)
            self.assertEqual(self.manager.engine.private_state(),before)

    def test_unknown_blocks_new_intents_including_startup(self):
        self.apply();self.manager.on_frame(fixtures.frame(NOW+10))
        state=self.manager.engine.private_state();self.assertEqual(state['orders'],{})
        self.assertEqual(state['wallet'],{'ETH':D(1)})
        self.assertEqual(state['auto']['last_reason'],'GLOBAL_PROFIT_UNKNOWN_OR_BELOW_TARGET_HOLD')

    def test_qualifying_intent_pins_revision_and_is_post_only_with_native_reservation(self):
        self.funded();self.apply();self.manager.on_frame(evidence_frame(),usd_reference=usd())
        state=self.manager.engine.private_state();order=list(state['orders'].values())[-1]
        self.assertEqual((order['pair'],order['side']),('SOL-ETH','SELL'))
        self.assertEqual(order['global_policy_version'],1);self.assertEqual(order['source_budget'],D('.25'))
        self.assertEqual(order['state'],'PENDING_NEW');self.assertEqual(order['expires_at'],NOW+130)
        self.assertEqual(order['qualification']['state'],'CONDITIONAL_QUALIFIED')

    def test_direct_placement_cannot_bypass_applied_version_cap_or_profit_gate(self):
        self.funded();self.apply();engine=self.manager.engine;f=paper_frame(evidence_frame(),self.manager.config,planning=True)
        args=dict(reference='attempt',pair='SOL-ETH',side='SELL',source_budget=D('.25'),limit_price=D('1.2'),
            expires_at=NOW+100,frame=f,global_policy_version=1,usd_reference=usd())
        for change in (dict(global_policy_version=0),dict(global_policy_version=2),dict(source_budget=D('.2501')),
                dict(usd_reference=None),dict(frame=evidence_frame())):
            with self.subTest(change=change),self.assertRaises(PaperBlocked):engine.place('attempt',**dict(args,**change))

    def test_existing_resting_order_is_unchanged_at_apply_then_reviewed_and_canceled(self):
        self.manager.on_frame(fixtures.frame());self.manager.on_frame(fixtures.frame(NOW+5))
        before=self.manager.engine.private_state();ref=next(iter(before['orders']))
        self.manager.apply_global(GlobalSettings(),at=NOW+10)
        after=self.manager.engine.private_state();self.assertEqual(after['orders'],before['orders'])
        self.manager.on_frame(fixtures.frame(NOW+15))
        order=self.manager.engine.private_state()['orders'][ref]
        self.assertEqual(order['state'],'PENDING_CANCEL');self.assertEqual(order['limit_price'],before['orders'][ref]['limit_price'])
        self.assertEqual(order.get('global_policy_version',0),0)

    def test_restart_restores_applied_revision_without_resuming_or_allocating_eth(self):
        self.funded();self.apply();before=self.manager.engine.private_state()
        restored=AutoPaper(self.manager.directory);after=restored.engine.private_state()
        self.assertEqual(after['mode'],'RECONCILIATION_REQUIRED')
        self.assertEqual(after['auto']['global_history'],before['auto']['global_history'])
        self.assertEqual(after['wallet'],before['wallet']);self.assertEqual(after['orders'],before['orders'])

    def test_corrupted_order_revision_or_pinned_evidence_cannot_restore_as_valid(self):
        self.funded();self.apply();self.manager.on_frame(evidence_frame(),usd_reference=usd())
        original=self.manager.engine.private_state();ref=list(original['orders'])[-1]
        for changes in (dict(global_policy_version=True),dict(global_policy_version=0),dict(global_policy_version=2),
                dict(qualification='untrusted'),dict(initial_slice_order=1)):
            state=deepcopy(original);state['orders'][ref].update(changes)
            with self.subTest(changes=changes),self.assertRaises((ValueError,PaperBlocked)):
                self.manager.engine._invariants(state)

    def test_public_global_status_is_quantity_free(self):
        self.apply();safe=self.manager.public();validate_public(safe)
        self.assertEqual(safe['policy'],GLOBAL_POLICY);self.assertEqual(safe['settings_version'],1)
        for name in ('min_net_usd','source_pct','initial_pct','qualification','global_history','funding_working_eth'):
            self.assertNotIn(name,safe)

    def start_return(self,minimum=D('.01')):
        self.funded();self.apply(min_net_usd=minimum)
        self.manager.on_frame(evidence_frame(),usd_reference=usd())
        self.manager.on_frame(evidence_frame(NOW+15),usd_reference=usd(NOW+15))
        state=self.manager.engine.private_state();order=list(state['orders'].values())[-1]
        self.assertEqual(order['state'],'OPEN')
        return order['reference']

    def explicit_return(self,ref,*,size=D('.25'),at=NOW+16):
        order=self.manager.engine.private_state()['orders'][ref]
        self.manager.engine.ingest(event('FILL',ref,'declared_return',at,dict(fill_id='declared_return',
            venue_order_id=order['venue_order_id'],price=order['limit_price'],size=size,size_in_quote=False,
            commission=size*order['limit_price']*D('.02'),fee_currency='ETH',liquidity='MAKER')))

    def test_completed_native_return_includes_original_entry_cost_and_actual_exit_fee_once(self):
        ref=self.start_return();self.explicit_return(ref)
        self.manager.on_frame(evidence_frame(NOW+17),usd_reference=usd(NOW+17))
        state=self.manager.engine.private_state();report=state['auto']['completed_rotations'][ref]
        self.assertEqual(report['net_eth'],D('.04275'));self.assertEqual(report['net_usd'],D('42.75'))
        self.assertEqual(report['allocation_eth'],D('.25125'));self.assertEqual(report['returned_eth'],D('.294'))
        self.assertEqual(report['state'],'MET');self.assertEqual(state['wallet']['SOL'],D('.25'))
        self.assertIsNone(report['actual_profit_usd'])

    def test_partial_then_canceled_return_below_floor_is_not_mislabeled_as_whole_rotation_profit(self):
        ref=self.start_return(D(30));self.explicit_return(ref,size=D('.125'))
        state=self.manager.engine.private_state()
        self.assertNotIn(ref,completed_reports(state,evidence_frame(NOW+17),usd(NOW+17)))
        self.assertEqual(self.manager.engine.available('ETH'),D('.4975'))
        self.manager.apply_global(GlobalSettings(min_net_usd=D(50)),at=NOW+18)
        self.manager.on_frame(evidence_frame(NOW+19),usd_reference=usd(NOW+19))
        self.assertEqual(self.manager.engine.private_state()['orders'][ref]['state'],'PENDING_CANCEL')
        self.manager.on_frame(evidence_frame(NOW+22),usd_reference=usd(NOW+22))
        state=self.manager.engine.private_state();report=state['auto']['completed_rotations'][ref]
        self.assertEqual(state['orders'][ref]['state'],'CANCELED')
        self.assertEqual(report['classification'],'SIMULATED_COMPLETED_ETH_RETURN_SLICE')
        self.assertEqual(report['net_usd'],D('21.375'));self.assertEqual(report['state'],'NOT_MET')
        self.assertEqual(report['policy_version'],1);self.assertEqual(report['minimum_usd'],D(30))
        self.assertEqual(state['wallet']['SOL'],D('.375'))

    def test_missing_or_late_completion_fx_remains_unknown_after_better_later_prices(self):
        ref=self.start_return();self.explicit_return(ref)
        state=self.manager.engine.private_state()
        for at,reference in ((NOW+17,None),(NOW+47,usd(NOW+47)),(NOW+29,usd(NOW+29))):
            with self.subTest(at=at):
                report=completed_reports(state,evidence_frame(at),reference)[ref]
                self.assertEqual(report['state'],'UNKNOWN');self.assertIsNone(report['net_usd'])
        context=state['auto'];context['completed_rotations']=completed_reports(state,evidence_frame(NOW+17),None)
        self.manager.engine.checkpoint_context(context)
        self.manager.on_frame(evidence_frame(NOW+20),usd_reference=usd(NOW+20))
        after=self.manager.engine.private_state()['auto']['completed_rotations'][ref]
        self.assertEqual(after,context['completed_rotations'][ref])
        altered=self.manager.engine.private_state()['auto'];altered['completed_rotations'][ref]['state']='MET'
        with self.assertRaises(ValueError):self.manager.engine.checkpoint_context(altered)

    def test_existing_return_that_still_meets_new_floor_retains_original_limit_and_policy(self):
        ref=self.start_return();before=self.manager.engine.private_state()['orders'][ref]
        self.manager.apply_global(GlobalSettings(min_net_usd=D(20)),at=NOW+18)
        self.manager.on_frame(evidence_frame(NOW+20),usd_reference=usd(NOW+20))
        state=self.manager.engine.private_state();after=state['orders'][ref]
        self.assertEqual(after,before);self.assertEqual(state['auto']['global_order_reviews'][ref],2)
        self.assertEqual(after['global_policy_version'],1)

    def test_global_touch_does_not_fill_and_stop_keeps_reserved_inventory(self):
        ref=self.start_return()
        for dt in (45,75,105):
            f=evidence_frame(NOW+dt,changes={'SOL-ETH':(D('1.2'),D('1.201'),NOW+dt)})
            self.manager.on_frame(f,usd_reference=usd(NOW+dt))
        state=self.manager.engine.private_state();self.assertEqual(state['simulated_fills'],1) # Declared funding receipt only.
        self.assertEqual(state['orders'][ref]['filled_base'],0)
        self.manager.pause(at=NOW+106);self.assertEqual(self.manager.engine.private_state()['mode'],'PAUSED')
        self.assertEqual(self.manager.engine.private_state()['orders'][ref]['reserved'],D('.25'))
        before=self.manager.engine.private_state()['orders']
        self.manager.on_frame(evidence_frame(NOW+108),usd_reference=usd(NOW+108))
        self.assertEqual(self.manager.engine.private_state()['orders'],before)

    def test_settings_before_current_frame_reject_late_frame_and_do_not_resume(self):
        self.funded();self.apply();before=self.manager.engine.private_state()
        self.manager.on_frame(evidence_frame(NOW+2),usd_reference=usd(NOW+2))
        self.assertEqual(self.manager.engine.private_state(),before)
        self.manager.pause(at=NOW+4);self.manager.apply_global(GlobalSettings(min_net_usd=D('.1')),at=NOW+5)
        self.assertEqual(self.manager.engine.private_state()['mode'],'PAUSED')

    def test_unfunded_view_and_disabled_frozen_direction_cannot_become_a_global_candidate(self):
        directions=fixtures.direction_defaults();directions['SOL_ETH']['enabled']=False
        other=AutoPaper(Path(self.temp.name)/'disabled')
        other.create(fixtures.config(directions=directions),at=NOW,funding=fixtures.funding())
        fixtures.AutoIntegration.fund_asset(other,'SOL');other.apply_global(GlobalSettings(),at=NOW+3)
        rows=global_candidates(other.engine,paper_frame(evidence_frame(),other.config,planning=True),other.config,GlobalSettings(),usd())
        self.assertEqual(rows['SOL_ETH']['reason'],'DIRECTION_DISABLED_IN_FROZEN_SESSION')
        self.assertEqual(rows['BTC_SOL']['reason'],'UNFUNDED_OR_NATIVE_CAP_UNAVAILABLE')
        with self.assertRaisesRegex(PaperBlocked,'GLOBAL_DIRECTION_DISABLED'):
            other.engine.place('disabled',reference='disabled',pair='SOL-ETH',side='SELL',source_budget=D('.25'),
                limit_price=D('1.2'),expires_at=NOW+100,frame=paper_frame(evidence_frame(),other.config,planning=True),
                global_policy_version=1,usd_reference=usd())

    def test_new_source_percentage_caps_future_orders_without_changing_funded_wallet(self):
        self.funded();self.apply();before=self.manager.engine.private_state()
        self.manager.apply_global(GlobalSettings(source_pct=D(25)),at=NOW+4)
        row=self.rows()['SOL_ETH'];self.assertEqual(row['source_budget'],D('.125'))
        after=self.manager.engine.private_state()
        for key in ('wallet','orders','limits'):self.assertEqual(after[key],before[key])
        with self.assertRaises(PaperBlocked):
            self.manager.apply_global(GlobalSettings(initial_pct=D(25)),at=NOW+5)

    def test_legacy_monitor_extension_is_accepted_but_partial_or_extra_global_fields_are_rejected(self):
        value=self.manager.public()
        for key in ('settings_version','completed_rotations','qualifying_rotations'):value.pop(key)
        validate_public(value)
        for changes in (dict(settings_version=1),dict(profit_usd=1),dict(orders=True),dict(policy=GLOBAL_POLICY)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate_public(dict(value,**changes))


class USDReferenceScan(unittest.TestCase):
    def test_extra_reference_get_preserves_six_native_books_graph_history_and_financial_ledger(self):
        with TemporaryDirectory() as folder:
            ledger,client,scanner=markets.network(folder);before=gui_fixtures.ledger_dump(ledger);requested=[]
            def collect(pairs,**kwargs):
                requested.extend(pairs)
                books,errors,elapsed=gui_fixtures.collector(client)([p for p in pairs if p!=USD_PAIR],**kwargs)
                books[USD_PAIR]=QuoteSnapshot(USD_PAIR,D(1000),D(1001),NOW,NOW,1)
                return books,errors,elapsed
            result=scanner.scan_growth(MakerConfig(('BTC','ADA','LINK','SOL'),D('.1'),observe_watchlist=True),
                now=NOW,collect=collect,allocation_draft=(AllocationRow('ETH',D(2)),),include_usd_reference=True)
            self.assertEqual(len(requested),7);self.assertEqual(requested[-1],USD_PAIR)
            self.assertEqual(result['quote_scheduling']['research_books'],6)
            self.assertEqual(result['quote_scheduling']['reference_books'],1)
            self.assertEqual(result['usd_reference'],usd(NOW))
            self.assertNotIn(USD_PAIR,result['research_frame']._quotes)
            self.assertNotIn(USD_PAIR,{r['pair'] for r in result['watched_markets']})
            with closing(sqlite3.connect(scanner.market_store.path)) as db:
                self.assertNotIn(USD_PAIR,{p[0] for p in db.execute('SELECT DISTINCT pair FROM market_quotes')})
            self.assertEqual(gui_fixtures.ledger_dump(ledger),before)

    def test_reference_transport_failure_leaves_native_observation_valid_and_reference_unknown(self):
        with TemporaryDirectory() as folder:
            _,client,scanner=markets.network(folder)
            def collect(pairs,**kwargs):
                books,_,elapsed=gui_fixtures.collector(client)([p for p in pairs if p!=USD_PAIR],**kwargs)
                errors=QuoteErrors({'HTTP_403':1});errors.by_product={USD_PAIR:'HTTP_403'}
                return books,errors,elapsed
            result=scanner.scan_growth(MakerConfig(('BTC',),D('.1'),observe_watchlist=True),now=NOW,
                collect=collect,allocation_draft=(AllocationRow('ETH',D(2)),),include_usd_reference=True)
            self.assertIsNone(result['usd_reference']);self.assertEqual(len(result['research_frame']._quotes),6)
            self.assertEqual(result['orders_submitted'],0)


class GlobalWorkspace(unittest.TestCase):
    setUp=gui_fixtures.SimpleGUI.setUp
    legacy_workspace=False

    def test_default_main_tabs_and_applied_preset_do_not_fund_or_change_risk_or_archived_records(self):
        app=self.app;panel=app.paper_panel;before=gui_fixtures.ledger_dump(app.ledger)
        self.assertEqual([app.tabs.tab(t,'text') for t in app.tabs.tabs()],
            ['Auto Trader','Trading Settings','Allocation','Research Archive'])
        self.assertEqual(app.tabs.tab(app.tabs.select(),'text'),'Auto Trader')
        self.assertEqual(panel.values['budget_percent'].get(),'50%')
        panel.global_values['source_pct'].set('25');panel.apply_global_settings()
        panel.global_values['source_pct'].set('40');panel._profit_preset('0.10')
        self.assertEqual(panel.global_applied_draft.min_net_usd,D('.10'))
        self.assertEqual(panel.global_applied_draft.source_pct,D(25)) # Unapplied risk draft is separate.
        self.assertIn('$0.10',panel.applied_summary.get());self.assertIsNone(app.paper.engine)
        self.assertEqual(gui_fixtures.ledger_dump(app.ledger),before)
        for w,h in ((1380,900),(1040,780)):
            self.root.geometry(f'{w}x{h}');self.root.update()
            self.assertTrue(panel.market_tabs.winfo_viewable())
            self.assertLess(panel.market_tabs.winfo_rooty(),self.root.winfo_rooty()+h-120)
            self.assertTrue(app._logo_source.transparency_get(0,0))
        app.tabs.select(app.tabs.tabs()[-1]);app.archive_tabs.select(app.research_page);self.root.update()
        self.assertTrue(app.chart.winfo_viewable());self.assertTrue(app.counter_label.winfo_viewable())

    def test_start_requires_applied_global_settings_and_first_slice_is_not_halved_twice(self):
        app=self.app;_,_,scanner=markets.network(self.temp.name);app.scanner=scanner;app.connected=True
        app.allocation_editor.clock=lambda:NOW
        with patch('coincat_app.time.time',return_value=NOW):app._render_wallet()
        panel=app.paper_panel;self.assertEqual(D(panel.values['amount_eth'].get()),D(1))
        panel.opt_in.set(True)
        with patch('coincat_app.time.time',return_value=NOW),patch.object(app,'_scan'):
            app._start_auto_paper();self.assertIsNone(app.paper.engine)
            panel.apply_global_settings();app._start_auto_paper()
        state=app.paper.engine.private_state();self.assertEqual(state['wallet'],{'ETH':D(1)})
        self.assertEqual(state['funding_working_eth'],D(2));self.assertEqual(state['funding_fraction'],D('.5'))
        self.assertTrue(state['auto']['global_initial_slice']);self.assertEqual(state['orders'],{})
        self.root.geometry('1040x780');self.root.update()
        self.assertGreaterEqual(panel.market_tabs.winfo_height(),150)
