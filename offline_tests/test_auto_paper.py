"""All-market opt-in integration and adversarial uncalibrated PAPER scenarios."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json,sqlite3,unittest,uuid

from coincat_adaptive_eth import Frame
from coincat_auto_paper import AutoPaper,public_status,validate_public
from coincat_paper_engine import PaperBlocked,TERMINAL
from coincat_paper_policy import (AutoConfig,POLICY,SHORT_POLICY,DIRECTIONS,BY_ID,KICKOFFS,MODELS,direction_defaults,
    candidates,paper_frame,reference_costs,eth_mark,select_candidate)
from coincat_paper_venue import StressVenue,event
from coincat_working_allocation import AllocationRow
from coincat_watchlist import WATCH_PAIRS,ETH_PAIRS
from coincat_monitor import capture,encode,validate
from coincat_simple_diagnostics import make_report
from offline_tests.test_adaptive_eth import inputs
from offline_tests.test_native_receipts import NOW
from offline_tests import gui_fixtures as fixtures
from offline_tests.test_v100_eth_growth import prepare,run_growth


def frame(at=NOW,*,pair=None,changes=None,tier=None,rules=None,catalog=None,excluded=()):
    x=inputs(at=at,fee='.005',evidence=False)
    for p in x['_rules'].values():p.update(base_increment='.0001',base_min_size='.0001')
    selected=list(ETH_PAIRS)+[p for p in WATCH_PAIRS if p not in ETH_PAIRS and p!=pair][:2]
    if pair and pair not in selected:selected=selected[:5]+[pair]
    x['_quotes']={p:(D(1),D('1.001'),at) for p in selected}
    x['_quotes'].update(changes or {})
    for product,values in (rules or {}).items():x['_rules'][product].update(values)
    x['_tier'].update(tier or {});x['_excluded']=excluded
    if catalog is not None:x['_catalog']=catalog
    return Frame(**x)


def config(**changes):
    return replace(AutoConfig(D(1),direction_defaults(),opt_in=True,duration_s=3600),**changes)


def funding(at=NOW,working=D(1)):
    return dict(balances={'ETH':D(2),'BTC':D(50),'SOL':D(100)},balances_at=at,
        draft=(AllocationRow('ETH',working,D('.5'),D('.5')),))


class AutoIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.manager=self.create('main')

    def create(self,name,settings=None):
        # Exercise portable fixture paths on Linux as well as Windows. Case
        # parameters belong in subTest labels, never filesystem components.
        self.assertRegex(name,r'\A[A-Za-z0-9_-]+\Z')
        manager=AutoPaper(Path(self.temp.name)/name)
        with patch('coincat_auto_paper.uuid.uuid4',return_value=uuid.UUID(int=1)):
            manager.create(settings or config(),at=NOW,funding=funding())
        return manager

    def start_kick(self,manager=None,settings=None):
        manager=manager or self.manager
        manager.on_frame(frame())
        manager.on_frame(frame(NOW+5))
        self.assertIsNone(manager.last_problem)
        return manager.engine.private_state()['auto']['kickoff_reference']

    @staticmethod
    def fund_asset(manager,asset):
        if asset=='ETH':return
        view=next(v for v in DIRECTIONS if v['source']=='ETH' and v['target']==asset)
        f=frame();reference='fund_'+asset
        manager.engine.place('intent_'+reference,reference=reference,pair=view['pair'],side=view['side'],
            source_budget=D(1),limit_price=D('1.001') if view['side']=='SELL' else D(1),
            expires_at=NOW+300,frame=f,target_cap_from_receipt=True)
        venue='venue_'+reference
        manager.engine.ingest(event('ACK',reference,'ack_'+reference,NOW+1,dict(venue_order_id=venue)))
        price=D('1.001') if view['side']=='SELL' else D(1)
        # A separately declared .5-base execution and matching terminal partial.
        manager.engine.ingest(event('FILL',reference,'fill_'+reference,NOW+2,dict(fill_id='fill_'+reference,
            venue_order_id=venue,price=price,size=D('.5'),size_in_quote=False,commission=D('.0025025')
            if view['side']=='SELL' else D('.0025'),fee_currency=view['pair'].split('-')[1],liquidity='MAKER')))
        manager.engine.ingest(event('CANCEL_ACK',reference,'cancel_'+reference,NOW+3,
            dict(venue_order_id=venue,cumulative_base=D('.5'))))

    def test_fourteen_exact_views_share_seven_actual_products_no_inverse_ids(self):
        self.assertEqual(len(DIRECTIONS),14);self.assertEqual(len(BY_ID),14)
        self.assertEqual({v['pair'] for v in DIRECTIONS},set(WATCH_PAIRS))
        self.assertEqual({(v['pair'],v['side']) for v in DIRECTIONS},{(p,s) for p in WATCH_PAIRS for s in ('BUY','SELL')})
        for view in DIRECTIONS:
            base,quote=view['pair'].split('-')
            self.assertEqual((view['source'],view['target']),(quote,base) if view['side']=='BUY' else (base,quote))
        self.assertEqual(KICKOFFS,('ETH_BTC','ETH_SOL','ETH_LINK','ETH_ADA'))

    def test_initial_wallet_is_only_approved_eth_after_existing_carve_outs(self):
        self.assertEqual(self.manager.engine.private_state()['wallet'],{'ETH':D(1)})
        self.assertEqual(self.manager.engine.available('BTC'),0)
        for index,changes in enumerate((dict(amount_eth=D('1.01')),dict(opt_in=False))):
            with self.subTest(changes=changes),self.assertRaises(PaperBlocked):self.create('funding_'+str(index),config(**changes))
        self.assertEqual(self.manager.engine.private_state()['limits']['source_caps'],{'ETH':D(1)})

    def test_all_fourteen_native_intents_admit_only_funded_source_and_canonical_rules(self):
        for view in DIRECTIONS:
            with self.subTest(view=view['id']):
                m=self.create(view['id']);self.fund_asset(m,view['source'])
                f=frame(NOW+10,pair=view['pair'])
                row=candidates(m.engine,f,m.config)[view['id']]
                self.assertIn('plan',row,row)
                before=m.engine.private_state()['wallet']
                m.engine.place('test_direction',reference='direction',pair=view['pair'],side=view['side'],
                    source_budget=row['source_budget'],limit_price=row['limit_price'],expires_at=NOW+300,
                    frame=paper_frame(f,m.config,planning=True),target_cap_from_receipt=True)
                order=m.engine.private_state()['orders']['direction']
                self.assertEqual(order['source'],view['source']);self.assertEqual(order['target'],view['target'])
                self.assertEqual(m.engine.private_state()['wallet'],before)
                self.assertEqual(order['plan_receipt']['input_asset'],view['source'])
                self.assertNotIn('approx_usd_notional',order['plan_receipt'])

    def test_all_four_kickoffs_are_prompt_once_only_and_do_not_wait_for_cycle_forecast(self):
        for choice in KICKOFFS:
            with self.subTest(choice=choice):
                m=self.create(choice,config(kickoff=choice));m.on_frame(frame())
                state=m.engine.private_state();self.assertEqual(len(state['orders']),1)
                ref=state['auto']['kickoff_reference'];order=state['orders'][ref];view=BY_ID[choice]
                self.assertEqual((order['pair'],order['side']),(view['pair'],view['side']))
                self.assertEqual(order['state'],'PENDING_NEW')
                for _ in range(3):m.on_frame(frame())
                m.on_frame(frame(NOW+5));m.on_frame(frame(NOW+30))
                self.assertEqual(len(m.engine.private_state()['orders']),1)
                self.assertEqual(m.engine.private_state()['auto']['kickoff_reference'],ref)

    def test_blocked_chosen_kickoff_has_no_silent_fallback_or_minimum_upscaling(self):
        self.manager.on_frame(frame(catalog=tuple(p for p in WATCH_PAIRS if p!='ETH-BTC')))
        self.assertEqual(self.manager.engine.private_state()['orders'],{})
        self.assertEqual(self.manager.engine.private_state()['wallet'],{'ETH':D(1)})
        self.assertEqual(self.manager.engine.private_state()['auto']['last_reason'],'NOT_IN_AUTHENTICATED_CATALOG')
        m=self.create('too_small',config(amount_eth=D('.00001')))
        m.on_frame(frame(rules={'ETH-BTC':{'base_min_size':'.1'}}))
        self.assertEqual(m.engine.private_state()['orders'],{})
        self.assertIn('BLOCKED_MINIMUM',m.engine.private_state()['auto']['last_reason'])

    def test_missing_stale_or_outside_ceiling_fees_block_without_zero_fallback(self):
        for index,values in enumerate(({'fresh':False},{'maker':None},{'maker':D('-.001')},
                {'captured_at':NOW-7201},{'maker':D('.04')})):
            m=self.create('fees'+str(index));m.on_frame(frame(tier=values))
            self.assertEqual(m.engine.private_state()['orders'],{})
            self.assertEqual(m.engine.private_state()['wallet'],{'ETH':D(1)})

    def test_all_fourteen_views_reject_permissions_rules_exclusions_and_unknown_listing(self):
        for view in DIRECTIONS:
            for index,change in enumerate(({'view_only':True},{'base_increment':'0'},{'product_type':'FUTURE'})):
                m=self.create('invalid_'+view['id']+'_'+str(index));self.fund_asset(m,view['source'])
                row=candidates(m.engine,frame(NOW+10,pair=view['pair'],rules={view['pair']:change}),m.config)[view['id']]
                self.assertEqual(row['state'],'BLOCKED')

    def test_quote_touch_even_many_observations_never_schedules_a_fill(self):
        reference=self.start_kick()
        for dt in range(10,400,5):
            self.manager.on_frame(frame(NOW+dt,changes={'ETH-BTC':(D('1.001'),D('1.002'),NOW+dt)}))
        state=self.manager.engine.private_state()
        self.assertEqual(state['simulated_fills'],0);self.assertEqual(state['wallet'],{'ETH':D(1)})
        self.assertEqual(state['orders'][reference]['state'],'OPEN')
        self.assertFalse(any(p['kind']=='FILL' for p in state['auto']['pending']))

    def test_strict_penetration_still_needs_rest_sustained_samples_and_seeded_queue_gate(self):
        self.start_kick()
        for dt in (10,15,20):
            self.manager.on_frame(frame(NOW+dt,changes={'ETH-BTC':(D('1.01'),D('1.011'),NOW+dt)}))
        self.assertEqual(self.manager.engine.status()['simulated_fills'],0)

    def test_no_fill_baseline_keeps_eth_and_charges_no_execution_fee(self):
        m=self.create('no_fill',config(model='NO_FILL_V1'));self.start_kick(m)
        for dt in range(10,400,10):m.on_frame(frame(NOW+dt,changes={'ETH-BTC':(D('1.01'),D('1.011'),NOW+dt)}))
        state=m.engine.private_state()
        self.assertEqual(state['wallet'],{'ETH':D(1)});self.assertEqual(state['simulated_fills'],0)
        self.assertEqual(state['auto']['performance']['fees'],{})
        self.assertEqual(state['auto']['performance']['midpoint_delta_eth'],0)

    def test_resting_review_retains_order_without_forced_churn_or_renewed_expiry(self):
        reference=self.start_kick();before=self.manager.engine.private_state()['orders'][reference]
        for dt in (30,60,90):self.manager.on_frame(frame(NOW+dt))
        state=self.manager.engine.private_state()
        self.assertEqual(len(state['orders']),1);self.assertEqual(state['orders'][reference]['expires_at'],before['expires_at'])
        self.assertEqual(state['auto']['last_reason'],'REVIEW_RETAIN_RESTING_ORDER_OR_LOCKED_PARTIAL')
        self.assertGreaterEqual(state['auto']['reviews'],4)

    def test_post_only_book_movement_before_arrival_rejects_without_taker_fill(self):
        self.manager.on_frame(frame())
        self.manager.on_frame(frame(NOW+5,changes={'ETH-BTC':(D('1.002'),D('1.003'),NOW+5)}))
        state=self.manager.engine.private_state()
        self.assertEqual(next(iter(state['orders'].values()))['state'],'REJECTED')
        self.assertEqual(state['wallet'],{'ETH':D(1)});self.assertEqual(state['simulated_fills'],0)

    def test_restore_after_grant_never_resends_or_duplicates_kickoff(self):
        self.manager.on_frame(frame());state=self.manager.engine.private_state();reference=state['auto']['kickoff_reference']
        restored=AutoPaper(self.manager.directory)
        self.assertEqual(restored.public()['state'],'RECONCILIATION_REQUIRED')
        self.assertEqual(restored.engine.pending_commands(),[])
        with self.assertRaisesRegex(PaperBlocked,'RECONCILIATION_REQUIRED'):restored.start(at=NOW+10)
        restored.reconcile(at=NOW+10)
        self.assertEqual(restored.public()['state'],'PAUSED')
        self.assertEqual(restored.engine.private_state()['limits']['expires_at'],state['limits']['expires_at'])
        restored.start(at=NOW+15);restored.on_frame(frame(NOW+20))
        self.assertEqual(len(restored.engine.private_state()['orders']),1)
        self.assertEqual(restored.engine.private_state()['auto']['kickoff_reference'],reference)

    def test_restore_open_order_and_pause_keep_reservations_and_no_auto_resume(self):
        reference=self.start_kick();self.manager.pause(at=NOW+10)
        self.assertEqual(self.manager.engine.available('ETH'),0)
        before=self.manager.engine.private_state()
        restored=AutoPaper(self.manager.directory);restored.reconcile(at=NOW+20)
        after=restored.engine.private_state()
        self.assertEqual(after['wallet'],before['wallet']);self.assertEqual(after['orders'][reference]['reserved'],1)
        self.assertEqual(restored.public()['state'],'PAUSED');self.assertEqual(restored.engine.pending_commands(),[])

    def test_finite_horizon_is_final_and_never_replaced_by_later_favorable_mark(self):
        m=self.create('horizon',config(model='NO_FILL_V1',duration_s=60));self.start_kick(m)
        m.on_frame(frame(NOW+60));before=deepcopy(m.engine.private_state()['auto']['horizon'])
        m.on_frame(frame(NOW+500,changes={'ETH-BTC':(D('.5'),D('.5001'),NOW+500)}))
        self.assertEqual(m.engine.private_state()['auto']['horizon'],before)
        self.assertEqual(before['deadline'],NOW+60);self.assertEqual(before['state'],'CONDITIONAL_OUTCOME')
        self.assertEqual(m.engine.private_state()['wallet'],{'ETH':D(1)})

    def test_missed_horizon_and_quote_gaps_cannot_rewrite_original_deadline(self):
        self.start_kick();deadline=self.manager.engine.private_state()['limits']['expires_at']
        self.manager.on_frame(frame(NOW+40,changes={'ETH-BTC':(D(1),D('1.001'),NOW-31)}))
        self.manager.on_frame(frame(deadline+31))
        self.assertEqual(self.manager.engine.private_state()['auto']['horizon']['state'],'MISSED_HORIZON')
        self.assertEqual(self.manager.engine.private_state()['limits']['expires_at'],deadline)

    def test_context_checkpoints_do_not_exhaust_event_budget_or_change_financial_fields(self):
        before=self.manager.engine.private_state()['wallet']
        with closing(sqlite3.connect(self.manager.engine.path)) as db:events_before=db.execute('SELECT COUNT(*) FROM paper_events').fetchone()[0]
        for i in range(5):
            c=self.manager.engine.private_state()['auto'];c['last_reason']='HOLD'+str(i)
            self.manager.engine.checkpoint_context(c)
        with closing(sqlite3.connect(self.manager.engine.path)) as db:events_after=db.execute('SELECT COUNT(*) FROM paper_events').fetchone()[0]
        self.assertEqual(events_before,events_after);self.assertEqual(self.manager.engine.private_state()['wallet'],before)
        with self.assertRaisesRegex(PaperBlocked,'CHECKPOINT_CANNOT_CHANGE'):
            self.manager.engine._apply('bad_context',{'kind':'AUTO_CONTEXT_CHECKPOINT'},lambda s:s['wallet'].update(ETH=D(99)),journal=False)
        self.assertEqual(self.manager.engine.private_state()['wallet'],before)

    def test_corrupt_active_index_cannot_create_a_replacement_wallet(self):
        index=self.manager.directory/'active_session.json';index.write_text('{private bad record')
        bad=AutoPaper(self.manager.directory);before=list(self.manager.directory.glob('paper_*.sqlite3'))
        self.assertEqual(bad.public()['state'],'UNAVAILABLE')
        with self.assertRaises(PaperBlocked):bad.create(config(),at=NOW,funding=funding())
        self.assertEqual(list(self.manager.directory.glob('paper_*.sqlite3')),before)

    def test_native_caps_come_from_receipts_without_crediting_future_proceeds(self):
        self.manager.on_frame(frame());state=self.manager.engine.private_state()
        self.assertIn('BTC',state['limits']['source_caps'])
        self.assertEqual(state['wallet'],{'ETH':D(1)})
        self.assertEqual(self.manager.engine.available('BTC'),0)
        self.assertEqual(state['limits']['source_caps']['BTC'],next(iter(state['orders'].values()))['plan_receipt']['output_quantity'])

    def test_every_membership_label_leaves_fee_evidence_and_rate_unchanged(self):
        rates=[]
        for label in ('None','Basic','Preferred','Premium'):
            m=self.create(label,config(membership=label));self.start_kick(m)
            rates.append(paper_frame(frame(),m.config).rates('MAKER'))
        self.assertEqual(rates,[D('.0055')]*4)

    def test_current_pass_boundary_rejects_extra_books_and_future_or_unsynchronized_dependencies(self):
        f=frame();quotes=dict(f._quotes);quotes['ADA-BTC']=(D(1),D('1.001'),NOW)
        with self.assertRaisesRegex(ValueError,'SCOPE'):paper_frame(Frame(NOW,f._catalog,f._rules,quotes,f._tier),config())
        row=candidates(self.manager.engine,frame(changes={'ETH-BTC':(D(1),D('1.001'),NOW+1)}),config(),kickoff=True)['ETH_BTC']
        self.assertEqual(row['state'],'BLOCKED');self.assertEqual(row['reason'],'QUOTE_FUTURE')

    def test_public_summary_is_quantity_free_and_rejects_unknown_private_fields(self):
        self.start_kick();safe=self.manager.public();validate_public(safe)
        for value in (dict(safe,balance='PRIVATE'),dict(safe,live_permission=1),dict(safe,fills=True)):
            with self.assertRaises(ValueError):validate_public(value)
        self.assertNotIn('wallet',str(safe));self.assertNotIn(self.manager.session_id,str(safe))
        self.assertEqual(safe['classification'],'SIMULATED_ASSUMPTION');self.assertFalse(safe['live_permission'])

    def test_seeded_adverse_partials_lock_proceeds_then_create_patient_return_without_hiding_open_loss(self):
        self.start_kick();saw_partial=False
        for dt in range(10,1600,10):
            self.manager.on_frame(frame(NOW+dt,changes={'ETH-BTC':(D('1.01'),D('1.011'),NOW+dt)}))
            state=self.manager.engine.private_state();seed=state['orders'][state['auto']['kickoff_reference']]
            if seed['state']=='PARTIAL':
                saw_partial=True;self.assertEqual(self.manager.engine.available('BTC'),0)
            if len(state['orders'])>1:break
        self.assertTrue(saw_partial);self.assertIsNone(self.manager.last_problem)
        self.assertEqual(seed['state'],'FILLED');self.assertEqual(len(state['orders']),2)
        after=list(state['orders'].values())[-1]
        self.assertEqual((after['pair'],after['side']),('ETH-BTC','BUY'))
        references,realized,fees=reference_costs(state)
        self.assertEqual(realized,0);self.assertGreater(fees['BTC'],0)
        self.assertLess(state['auto']['performance']['midpoint_delta_eth'],0)
        self.assertGreater(state['auto']['performance']['max_midpoint_drawdown_pct'],0)
        self.assertIsNone(state['auto']['performance']['recoverable_eth'])
        self.assertIsNone(state['auto']['performance']['actual_profit_eth'])

    def test_a_known_pending_final_fill_wins_the_delayed_cancel_race(self):
        ref=self.start_kick();engine=self.manager.engine;context=engine.private_state()['auto'];meta=context['venue'][ref]
        venue=meta['venue_id']
        engine.ingest(event('FILL',ref,'declared_half',NOW+10,dict(fill_id='declared_half',venue_order_id=venue,
            price=D('1.001'),size=D('.5'),size_in_quote=False,commission=D('.00275275'),fee_currency='BTC',liquidity='MAKER')))
        context=engine.private_state()['auto']
        payload=event('FILL',ref,'declared_final',NOW+21,dict(fill_id='declared_final',venue_order_id=venue,
            price=D('1.001'),size=D('.5'),size_in_quote=False,commission=D('.00275275'),fee_currency='BTC',liquidity='MAKER'))
        context['pending'].append(dict(kind='FILL',reference=ref,identity='declared_final',due_at=NOW+21,event=payload))
        engine.checkpoint_context(context);engine.request_cancel('cancel_request',ref)
        self.manager.venue.advance(engine,frame(NOW+20))
        self.manager.venue.settle_due(engine,at=NOW+30,frame=frame(NOW+30))
        state=engine.private_state()
        self.assertEqual(state['orders'][ref]['state'],'FILLED')
        self.assertEqual(state['wallet']['BTC'],D('.9954945'))
        self.assertEqual(state['simulated_fills'],2)
        self.assertEqual(state['auto']['pending'],[])

    def test_an_already_scheduled_fill_can_settle_after_stop_without_any_new_intent(self):
        ref=self.start_kick();engine=self.manager.engine;context=engine.private_state()['auto']
        payload=event('FILL',ref,'known_pending',NOW+11,dict(fill_id='known_pending',venue_order_id=context['venue'][ref]['venue_id'],
            price=D('1.001'),size=D('.5'),size_in_quote=False,commission=D('.00275275'),fee_currency='BTC',liquidity='MAKER'))
        context['pending'].append(dict(kind='FILL',reference=ref,identity='known_pending',due_at=NOW+11,event=payload))
        engine.checkpoint_context(context);self.manager.pause(at=NOW+10)
        self.manager.on_frame(frame(NOW+15))
        self.assertEqual(engine.private_state()['simulated_fills'],1)
        self.assertEqual(engine.private_state()['mode'],'PAUSED')
        self.assertEqual(len(engine.private_state()['orders']),1)
        self.assertEqual(engine.available('BTC'),0)

    def test_inspecting_history_never_marks_a_session_restored_or_mutates_bytes(self):
        self.start_kick();path=self.manager.engine.path;before=path.read_bytes()
        from coincat_paper_engine import PaperEngine
        state=PaperEngine.inspect(path)
        self.assertEqual(state['mode'],'ACTIVE');self.assertEqual(path.read_bytes(),before)
        self.assertTrue(self.manager.engine.local_events(state['auto']['kickoff_reference']))

    def test_same_seed_and_frames_reproduce_the_same_execution_history_after_restart(self):
        left=self.create('left');right=self.create('right')
        for dt in range(0,500,10):
            changes={} if dt<30 else {'ETH-BTC':(D('1.01'),D('1.011'),NOW+dt)}
            f=frame(NOW+dt,changes=changes)
            left.on_frame(f);right.on_frame(f)
        self.assertEqual(left.engine.private_state(),right.engine.private_state())

    def test_chronological_holdout_keeps_no_fill_and_adverse_results_with_unknown_recovery(self):
        from tools.AUTO_PAPER_HOLDOUT import evaluate
        results=evaluate(seeds=(1,),models=('NO_FILL_V1','CONSERVATIVE_STRESS_V1'),emit=lambda x:None)
        self.assertEqual(len(results),4)
        self.assertTrue(all(r['edge']=='NO_DEMONSTRATED_EDGE' for r in results))
        self.assertTrue(all(r['actual_profit_eth'] is None for r in results))
        for row in results:
            if row['model']=='NO_FILL_V1':
                self.assertEqual(row['fills'],0);self.assertEqual(row['fees'],{});self.assertEqual(row['midpoint_delta_eth'],0)
        adverse=next(r for r in results if r['scenario']=='ADVERSE_UNRECOVERED' and r['model']=='CONSERVATIVE_STRESS_V1')
        self.assertGreater(adverse['fills'],0);self.assertLess(adverse['midpoint_delta_eth'],0)
        self.assertIsNone(adverse['recoverable_eth'])
        self.assertGreater(adverse['partial_fill_events'],0)
        self.assertGreater(adverse['orders_with_partial_fills'],0)
        self.assertTrue(all(t>0 for t in adverse['completed_order_times_s']))

    def test_drawdown_retains_peak_to_trough_loss_after_a_positive_midpoint_mark(self):
        self.fund_asset(self.manager,'BTC')
        self.manager._sample(frame(NOW+10,changes={'ETH-BTC':(D('.5'),D('.5005'),NOW+10)}))
        peak=self.manager.engine.private_state()['auto']['performance']['marked_eth']
        self.assertGreater(peak,1)
        self.manager._sample(frame(NOW+20))
        metrics=self.manager.engine.private_state()['auto']['performance']
        self.assertEqual(metrics['peak_midpoint_eth'],peak)
        self.assertGreater(metrics['max_midpoint_drawdown_pct'],30)
        self.assertLess(metrics['marked_eth'],1)
        self.assertIsNone(metrics['recoverable_eth'])

    def test_policy_and_provider_parameters_are_frozen_and_recorded_before_first_intent(self):
        state=self.manager.engine.private_state();original=state['auto']['model_assumptions']
        self.assertFalse(original['observed_queue']);self.assertFalse(original['observed_volume'])
        self.assertEqual(original['min_cross_samples'],3)
        self.assertEqual(original['parameters']['probability'],D('.2'))
        altered=deepcopy(state['auto']);altered['config']['seed']=99
        with self.assertRaisesRegex(PaperBlocked,'FROZEN_PAPER_POLICY'):
            self.manager.engine.checkpoint_context(altered)
        self.manager.venue.parameters['probability']=D(1)
        self.manager.on_frame(frame())
        self.assertEqual(self.manager.engine.private_state()['orders'],{})
        self.assertEqual(self.manager.public()['state'],'UNAVAILABLE')

    def test_lookahead_changes_cannot_change_identical_prefix_decisions(self):
        left=self.create('prefix_left');right=self.create('prefix_right')
        for dt in (0,5,10,30):left.on_frame(frame(NOW+dt));right.on_frame(frame(NOW+dt))
        self.assertEqual(left.engine.private_state(),right.engine.private_state())
        prefix=deepcopy(left.engine.private_state()['orders'])
        left.on_frame(frame(NOW+40,changes={'ETH-BTC':(D('1.01'),D('1.011'),NOW+40)}))
        right.on_frame(frame(NOW+40,changes={'ETH-BTC':(D('.98'),D('.981'),NOW+40)}))
        self.assertEqual({k:v['created_at'] for k,v in left.engine.private_state()['orders'].items()},
            {k:v['created_at'] for k,v in prefix.items()})

    def test_zero_spread_post_only_block_does_not_fill_or_discard_the_chosen_kickoff(self):
        self.manager.on_frame(frame(changes={'ETH-BTC':(D(1),D(1),NOW)}))
        state=self.manager.engine.private_state()
        self.assertIsNone(state['auto']['kickoff_reference']);self.assertEqual(state['orders'],{})
        self.assertIsNone(self.manager.last_problem)
        self.assertIn('BLOCKED_POST_ONLY',state['auto']['last_reason'])

    def test_expired_far_patient_return_is_held_without_blind_repost_or_deadline_renewal(self):
        settings=direction_defaults();settings['BTC_ETH']['wait_s']=30
        m=self.create('return_expiry',config(directions=settings));self.fund_asset(m,'BTC')
        context=m.engine.private_state()['auto'];context['kickoff_reference']='fund_BTC'
        context['intent_meta']['fund_BTC']=dict(direction='ETH_BTC',kind='KICKOFF')
        m.engine.checkpoint_context(context)
        for dt in (10,15,40,45,70,100):m.on_frame(frame(NOW+dt))
        state=m.engine.private_state();self.assertIsNone(m.last_problem)
        self.assertEqual(len(state['orders']),2)
        resting=next(o for ref,o in state['orders'].items() if ref!='fund_BTC')
        self.assertEqual(resting['expires_at'],NOW+40);self.assertEqual(resting['state'],'CANCELED')
        self.assertEqual(state['limits']['expires_at'],NOW+3600)
        self.assertEqual(state['auto']['last_reason'],'HOLD_PRIOR_PATIENT_RETURN_EXPIRED_NO_BLIND_REPOST')

    def test_provider_rechecks_product_and_native_rules_before_generating_scenario_fills(self):
        ref=self.start_kick()
        for dt in range(10,180,10):
            f=frame(NOW+dt,changes={'ETH-BTC':(D('1.01'),D('1.011'),NOW+dt)},rules={'ETH-BTC':{'view_only':True}})
            self.manager.on_frame(f)
        state=self.manager.engine.private_state()
        self.assertEqual(state['simulated_fills'],0)
        self.assertEqual(state['auto']['venue'][ref]['data_state'],'PRODUCT_OR_NATIVE_RULE_UNAVAILABLE')
        other=self.create('arrival_restricted');other.on_frame(frame())
        other.on_frame(frame(NOW+5,rules={'ETH-BTC':{'view_only':True}}))
        self.assertEqual(next(iter(other.engine.private_state()['orders'].values()))['state'],'REJECTED')


class PaperGUI(unittest.TestCase):
    setUp=fixtures.SimpleGUI.setUp

    def ready(self):
        app=self.app;_,client,scanner=prepare(self.temp.name);app.scanner=scanner;app.connected=True
        app.allocation_editor.clock=lambda:NOW
        with patch('coincat_app.time.time',return_value=NOW):app._render_wallet()
        return app,client,scanner

    def test_seven_books_and_fourteen_populated_views_do_not_fetch_or_create_wallets(self):
        app=self.app;panel=app.paper_panel
        self.assertFalse(panel.opt_in.get());self.assertEqual(len(panel.market_tabs.tabs()),7)
        for pair,page in panel.pages.items():
            panel.market_tabs.select(page);self.root.update()
            self.assertEqual(len(page.direction_tabs.tabs()),2)
            for tab in page.direction_tabs.tabs():page.direction_tabs.select(tab);self.root.update_idletasks()
            self.assertIn('UNKNOWN',page.book_trees['Bid'].item(page.book_trees['Bid'].get_children()[0],'values'))
        self.assertEqual(set(panel.direction_pages),set(BY_ID))
        self.assertIsNone(app.paper.engine)
        self.assertFalse(app.paper.directory.exists())

    def test_start_from_normal_workflow_uses_exact_custom_paper_budget_without_changing_manual_controls(self):
        app,client,scanner=self.ready();before=fixtures.ledger_dump(app.ledger);manual=app.mixer.values()
        app.paper_panel.values['budget_percent'].set('Exact custom');app.paper_panel.values['amount_eth'].set('.01')
        app.paper_panel.opt_in.set(True)
        with patch('coincat_app.time.time',return_value=NOW),patch.object(app,'_scan') as scan:
            app._start_auto_paper();scan.assert_called_once()
        self.assertTrue(app.running);self.assertTrue(app.paper_observe);self.assertIsNone(app.applied_config)
        self.assertEqual(app.paper.engine.private_state()['initial_eth'],D('.01'))
        self.assertEqual(app.mixer.values(),manual);self.assertEqual(fixtures.ledger_dump(app.ledger),before)
        self.assertEqual(app._paper_scan_config().amount_eth,D('.01'))
        self.assertTrue(app._paper_scan_config().observe_watchlist)

    def test_default_percentage_changes_only_paper_draft_and_custom_is_preserved(self):
        app,_,_=self.ready();working=app._funding()['row']['working']
        self.assertEqual(D(app.paper_panel.values['amount_eth'].get()),working*D('.1'))
        app.paper_panel.values['budget_percent'].set('Exact custom');app.paper_panel.values['amount_eth'].set('.012345678901')
        app.paper_panel.update_budget_default()
        self.assertEqual(app.paper_panel.values['amount_eth'].get(),'.012345678901')

    def test_stop_rejects_late_scan_before_any_kickoff_and_preserves_wallet(self):
        app,client,scanner=self.ready();panel=app.paper_panel
        panel.values['amount_eth'].set('.01');panel.opt_in.set(True)
        with patch('coincat_app.time.time',return_value=NOW),patch.object(app,'_scan'):
            app._start_auto_paper();generation=app.generation
            result=scanner.scan_growth(app._paper_scan_config(),now=NOW,collect=fixtures.collector(client),
                allocation_draft=app.allocation_editor.parameters()['allocation_draft'])
            app._stop();app.jobs.put(('scan',generation,result,None));app._poll()
        self.assertEqual(app.paper.engine.private_state()['orders'],{})
        self.assertEqual(app.paper.engine.private_state()['wallet'],{'ETH':D('.01')})
        self.assertFalse(app.running)

    def test_monitor_v3_optional_extension_redacts_native_ui_and_rejects_extra_nested_fields(self):
        app,_,_=self.ready();app.paper_public=public_status(dict(state='ACTIVE',orders=2,fills=3))
        snap=capture(app,session='a'*32,sequence=1,now=NOW);validate(snap)
        self.assertEqual(snap['schema'],'coincat-monitor/v3');self.assertEqual(snap['auto_paper']['fills'],3)
        legacy=deepcopy(snap);legacy.pop('auto_paper');validate(legacy)
        snap['auto_paper']['wallet']='PRIVATE'
        with self.assertRaises(ValueError):validate(snap)
        report=make_report(app,now=NOW)
        self.assertIn('COMPLETE (8/8)',report);self.assertIn('auto_paper',report)
        self.assertNotIn('wallet',str(public_status({'wallet':'PRIVATE'})))

    def test_actual_accepted_scan_starts_kickoff_with_no_extra_http_or_financial_writes(self):
        app,client,scanner=self.ready();app.paper_panel.values['amount_eth'].set('.01');app.paper_panel.opt_in.set(True)
        f=frame();client.rules=f._rules
        client.q={p:(D(1),D('1.001'),NOW) for p in WATCH_PAIRS}
        scanner.refresh(now=NOW,force_catalog=True)
        before=fixtures.ledger_dump(app.ledger);reads=list(client.calls)
        with patch('coincat_app.time.time',return_value=NOW),patch.object(app,'_scan'):
            app._start_auto_paper();generation=app.generation
            result=scanner.scan_growth(app._paper_scan_config(),now=NOW,collect=fixtures.collector(client),
                allocation_draft=app.allocation_editor.parameters()['allocation_draft'])
            app.jobs.put(('scan',generation,result,None));app._poll()
        self.assertEqual(len(app.paper.engine.private_state()['orders']),1)
        order=next(iter(app.paper.engine.private_state()['orders'].values()))
        self.assertEqual((order['pair'],order['side']),('ETH-BTC','SELL'))
        self.assertEqual(client.calls,reads);self.assertEqual(fixtures.ledger_dump(app.ledger),before)
        self.assertLessEqual(result['quote_scheduling']['research_books'],6)
        self.assertEqual(result['quote_scheduling']['request_limit'],16)
        self.assertEqual(result['orders_submitted'],0)

    def test_settings_and_tabs_preserve_frozen_session_and_exact_custom_amount(self):
        app,_,_=self.ready();panel=app.paper_panel;panel.values['amount_eth'].set('.012345678901');panel.opt_in.set(True)
        with patch('coincat_app.time.time',return_value=NOW),patch.object(app,'_scan'):app._start_auto_paper()
        before=app.paper.engine.private_state();panel.settings()
        for page in panel.pages.values():panel.market_tabs.select(page);self.root.update()
        self.assertEqual(app.paper.engine.private_state(),before)
        self.assertEqual(panel.values['amount_eth'].get(),'.012345678901')
        self.assertTrue(all('disabled' in w.state() for w in panel.session_widgets if w.winfo_exists()))
        panel.settings_window.destroy()

    def test_short_order_settings_start_through_accepted_scan_and_keep_financial_records_unchanged(self):
        app,client,scanner=self.ready();panel=app.paper_panel;panel.settings()
        self.assertTrue(all('disabled' in w.state() for w in panel.short_widgets))
        panel.values['order_policy'].set('Short-lived / net ETH target');panel._freeze()
        self.assertTrue(all('disabled' not in w.state() for w in panel.short_widgets))
        panel.values['amount_eth'].set('.01');panel.opt_in.set(True)
        f=frame();client.rules=f._rules;client.q={p:(D(1),D('1.001'),NOW) for p in WATCH_PAIRS}
        scanner.refresh(now=NOW,force_catalog=True);before=fixtures.ledger_dump(app.ledger);reads=list(client.calls)
        with patch('coincat_app.time.time',return_value=NOW),patch.object(app,'_scan'):
            app._start_auto_paper();result=scanner.scan_growth(app._paper_scan_config(),now=NOW,
                collect=fixtures.collector(client),allocation_draft=app.allocation_editor.parameters()['allocation_draft'])
            app.jobs.put(('scan',app.generation,result,None));app._poll()
        state=app.paper.engine.private_state();order=next(iter(state['orders'].values()))
        self.assertEqual(state['auto']['policy'],SHORT_POLICY);self.assertEqual(order['expires_at'],NOW+120)
        self.assertEqual(client.calls,reads);self.assertEqual(fixtures.ledger_dump(app.ledger),before)
        snap=capture(app,session='a'*32,sequence=1,now=NOW);validate(snap)
        self.assertEqual(snap['auto_paper']['policy'],SHORT_POLICY)
        self.assertNotIn('campaign_root',str(snap));self.assertNotIn('order_ttl_s',str(snap))
        self.assertTrue(all('disabled' in w.state() for w in panel.session_widgets if w.winfo_exists()))

    def test_legacy_session_configuration_keeps_patient_policy_and_frozen_original_wait(self):
        app,_,_=self.ready();panel=app.paper_panel
        old=config(amount_eth=D('.01'));app.paper.create(old,at=NOW,funding=funding())
        panel.values['order_policy'].set('Short-lived / net ETH target');panel.from_config(app.paper.config)
        panel.settings();self.assertEqual(panel.values['order_policy'].get(),'Patient target')
        self.assertEqual(app.paper.config.directions['ETH_BTC']['wait_s'],86400)
        self.assertNotIn('policy',app.paper.config.frozen())
        panel.values['order_ttl_s'].set('unused invalid draft')
        self.assertEqual(panel.configuration().frozen(),old.frozen())
        self.assertTrue(all('disabled' in w.state() for w in panel.session_widgets if w.winfo_exists()))

    def test_shutdown_waits_for_canceled_read_worker_and_cannot_apply_its_late_result(self):
        import threading,time
        app=self.app;entered=threading.Event();release=threading.Event()
        def work():
            entered.set()
            if not release.wait(2):raise AssertionError('Synthetic worker not released')
            return {'state':'CANCELLED'}
        app._submit('scan',work);self.assertTrue(entered.wait(1));app._close()
        self.assertFalse(app.shutdown_complete.is_set());self.assertTrue(app.closed)
        release.set();deadline=time.monotonic()+2
        while not app.shutdown_complete.is_set() and time.monotonic()<deadline:
            app.root.tk.call('update');time.sleep(.005)
        self.assertTrue(app.shutdown_complete.is_set());self.assertFalse(app.worker_thread.is_alive())
        self.assertIsNone(app.last_result);self.assertIsNone(app.paper.engine)

    def test_nontransient_read_failure_pauses_paper_without_resetting_its_identity_or_budget(self):
        from coincat_recovery import failure
        app,_,_=self.ready();app.paper_panel.values['amount_eth'].set('.01');app.paper_panel.opt_in.set(True)
        with patch('coincat_app.time.time',return_value=NOW),patch.object(app,'_scan'):
            app._start_auto_paper();before=app.paper.engine.private_state()
            app._handle_failure('scan',failure(ValueError('PRIVATE_CONFIGURATION_DETAIL')))
        after=app.paper.engine.private_state()
        self.assertFalse(app.running);self.assertEqual(after['mode'],'PAUSED')
        self.assertEqual(after['wallet'],before['wallet']);self.assertEqual(after['limits'],before['limits'])
        self.assertEqual(after['auto']['session'],before['auto']['session'])
        self.assertNotIn('PRIVATE_CONFIGURATION_DETAIL',app.status.get())


class ShortLivedOrders(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.serial=0
        self.manager=self.create()

    def create(self,**changes):
        self.serial+=1;manager=AutoPaper(Path(self.temp.name)/('case_'+str(self.serial)))
        settings=config(policy=SHORT_POLICY,model='NO_FILL_V1',**changes)
        with patch('coincat_auto_paper.uuid.uuid4',return_value=uuid.UUID(int=1)):
            manager.create(settings,at=NOW,funding=funding())
        return manager

    def advance(self,dt,manager=None,*,price=None,missing=False):
        manager=manager or self.manager;at=NOW+dt
        f=frame(at,changes={} if price is None else {'ETH-BTC':(D(price),D(price)+D('.001'),at)})
        if missing:
            f=Frame(at,f._catalog,f._rules,{p:q for p,q in f._quotes.items() if p!='ETH-BTC'},f._tier)
        manager.on_frame(f);self.assertIsNone(manager.last_problem)
        return manager.engine.private_state()

    def opened(self,manager=None):
        manager=manager or self.manager;self.advance(0,manager);state=self.advance(5,manager)
        return next(iter(state['orders']))

    def fill_seed(self):
        ref=self.opened();order=self.manager.engine.private_state()['orders'][ref]
        self.manager.engine.ingest(event('FILL',ref,'declared_seed_fill',NOW+10,dict(fill_id='declared_seed_fill',
            venue_order_id=order['venue_order_id'],price=order['limit_price'],size=order['base_size'],
            size_in_quote=False,commission=D('.0055055'),fee_currency='BTC',liquidity='MAKER')))
        return ref

    def test_short_config_is_versioned_without_changing_legacy_frozen_identity(self):
        old=config();stored=old.frozen()
        self.assertNotIn('policy',stored);self.assertNotIn('order_ttl_s',stored)
        self.assertEqual(AutoConfig(**stored).frozen(),stored)
        self.assertEqual(self.manager.config.frozen()['policy'],SHORT_POLICY)
        for change in (dict(order_ttl_s=True),dict(order_ttl_s=30),dict(min_rest_s=120),
                dict(reprice_bps=D('NaN')),dict(policy='UNKNOWN')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                replace(self.manager.config,**change).checked()

    def test_two_minute_child_retains_original_campaign_and_session_deadline(self):
        ref=self.opened();state=self.manager.engine.private_state();order=state['orders'][ref]
        self.assertEqual(order['expires_at'],NOW+120)
        self.assertEqual(state['auto']['intent_meta'][ref]['campaign_deadline'],NOW+3600)
        self.assertEqual(state['auto']['intent_meta'][ref]['campaign_root'],ref)

    def test_expired_unfilled_child_waits_for_cancel_then_retries_same_funded_campaign(self):
        ref=self.opened();self.advance(119)
        state=self.advance(120);self.assertEqual(state['orders'][ref]['state'],'PENDING_CANCEL')
        self.assertEqual(self.manager.engine.available('ETH'),0)
        state=self.advance(125);self.assertEqual(state['orders'][ref]['state'],'CANCELED')
        self.assertEqual(len(state['orders']),1)
        state=self.advance(150,price='1.03');new=list(state['orders'].values())[-1]
        self.assertEqual(len(state['orders']),2);self.assertEqual(new['limit_price'],D('1.031'))
        self.assertEqual(new['expires_at'],NOW+270)
        self.assertEqual(state['auto']['kickoff_reference'],ref)
        self.assertEqual(state['auto']['intent_meta'][new['reference']]['campaign_root'],ref)
        self.assertEqual(state['auto']['intent_meta'][new['reference']]['campaign_deadline'],NOW+3600)
        self.assertEqual(state['wallet'],{'ETH':D(1)});self.assertEqual(state['fills'],{})

    def test_market_move_requires_minimum_rest_and_confirmed_cancel_then_fresh_price(self):
        ref=self.opened();self.advance(29,price='1.01')
        state=self.advance(30,price='1.01');self.assertEqual(state['orders'][ref]['state'],'OPEN')
        state=self.advance(60,price='1.01');self.assertEqual(state['orders'][ref]['state'],'PENDING_CANCEL')
        self.assertEqual(len(state['orders']),1)
        state=self.advance(61,price='1.02');self.assertEqual(len(state['orders']),1)
        self.advance(65,price='1.03');state=self.advance(90,price='1.04')
        new=list(state['orders'].values())[-1]
        self.assertEqual(len(state['orders']),2);self.assertEqual(new['limit_price'],D('1.041'))
        self.assertEqual(state['orders'][ref]['state'],'CANCELED')
        self.assertEqual(new['source_budget'],D(1));self.assertEqual(state['wallet'],{'ETH':D(1)})

    def test_ordinary_reviews_and_small_tick_moves_retain_queue_and_order_identity(self):
        ref=self.opened();self.advance(30,price='1.0001');state=self.advance(60,price='1.0002')
        self.assertEqual(len(state['orders']),1);self.assertEqual(state['orders'][ref]['state'],'OPEN')
        self.assertEqual(state['auto']['venue'][ref]['accepted_at'],NOW+5)
        self.assertEqual(state['orders'][ref]['expires_at'],NOW+120)

    def test_faster_review_cannot_bypass_the_minimum_resting_period(self):
        manager=self.create(review_s=5);ref=self.opened(manager)
        state=self.advance(29,manager,price='1.01');self.assertEqual(state['orders'][ref]['state'],'OPEN')
        state=self.advance(34,manager,price='1.01');self.assertEqual(state['orders'][ref]['state'],'OPEN')
        state=self.advance(39,manager,price='1.01');self.assertEqual(state['orders'][ref]['state'],'PENDING_CANCEL')

    def test_all_fourteen_views_use_actual_resting_side_and_native_quote_units(self):
        for view in DIRECTIONS:
            with self.subTest(view=view['id']):
                manager=self.create();AutoIntegration.fund_asset(manager,view['source'])
                row=candidates(manager.engine,frame(NOW+10,pair=view['pair']),manager.config)[view['id']]
                self.assertIn('plan',row);self.assertEqual(row['market_limit_price'],D(1) if view['side']=='BUY' else D('1.001'))
                self.assertEqual(row['plan']['input_asset'],view['source'])
                if view['target']=='ETH':
                    self.assertEqual(row['limit_price'],row['market_limit_price'])
                    if row['state']=='CANDIDATE':self.assertGreaterEqual(row['plan']['output_quantity'],row['required_eth'])

    def test_stale_or_deferred_prices_cannot_trigger_replacement_or_a_fallback_seed(self):
        ref=self.opened();state=self.advance(60,missing=True)
        self.assertEqual(state['orders'][ref]['state'],'OPEN')
        self.advance(120,missing=True);self.advance(125,missing=True);state=self.advance(150,missing=True)
        self.assertEqual(state['orders'][ref]['state'],'CANCELED');self.assertEqual(len(state['orders']),1)
        self.assertEqual(state['auto']['kickoff_reference'],ref)

    def test_cancel_replacement_keeps_original_slice_with_a_nonfull_source_percentage(self):
        settings=direction_defaults();settings['ETH_BTC']['source_pct']=D(50)
        manager=self.create(directions=settings);ref=self.opened(manager)
        self.advance(60,manager,price='1.01');self.advance(65,manager,price='1.02')
        state=self.advance(90,manager,price='1.03')
        self.assertEqual(len(state['orders']),2)
        self.assertEqual([o['source_budget'] for o in state['orders'].values()],[D('.5'),D('.5')])
        self.assertEqual(state['wallet'],{'ETH':D(1)})
        self.assertEqual(state['auto']['kickoff_reference'],ref)

    def test_partial_proceeds_lock_until_cancel_and_do_not_create_another_initial_seed(self):
        ref=self.opened();order=self.manager.engine.private_state()['orders'][ref]
        self.manager.engine.ingest(event('FILL',ref,'declared_partial',NOW+10,dict(fill_id='declared_partial',
            venue_order_id=order['venue_order_id'],price=D('1.001'),size=D('.25'),size_in_quote=False,
            commission=D('.00137638'),fee_currency='BTC',liquidity='MAKER')))
        self.assertEqual(self.manager.engine.available('BTC'),0)
        state=self.advance(60,price='1.01');self.assertEqual(state['orders'][ref]['state'],'PENDING_CANCEL')
        self.assertEqual(self.manager.engine.available('BTC'),0)
        state=self.advance(65,price='1.02');self.assertEqual(state['orders'][ref]['state'],'CANCELED')
        self.assertGreater(self.manager.engine.available('BTC'),0)
        state=self.advance(90,price='1.03');self.assertEqual(len(state['orders']),1)
        self.assertEqual(state['wallet']['ETH'],D('.75'))
        self.assertEqual(state['auto']['performance']['fees']['BTC'],D('.00137638'))

    def test_final_fill_wins_cancel_race_and_cannot_recreate_the_initial_seed(self):
        ref=self.opened();engine=self.manager.engine;context=engine.private_state()['auto']
        payload=event('FILL',ref,'declared_final',NOW+61,dict(fill_id='declared_final',
            venue_order_id=context['venue'][ref]['venue_id'],price=D('1.001'),size=D(1),size_in_quote=False,
            commission=D('.0055055'),fee_currency='BTC',liquidity='MAKER'))
        context['pending'].append(dict(kind='FILL',reference=ref,identity='declared_final',due_at=NOW+61,event=payload))
        engine.checkpoint_context(context)
        self.advance(60,price='1.01');state=self.advance(65,price='1.02');self.advance(90,price='1.03')
        self.assertEqual(state['orders'][ref]['state'],'FILLED');self.assertEqual(len(engine.private_state()['orders']),1)
        self.assertEqual(state['wallet'],{'ETH':D(0),'BTC':D('.9954945')})
        self.assertEqual(state['simulated_fills'],1)

    def test_profit_target_below_market_is_hold_instead_of_a_far_away_exit(self):
        self.fill_seed();state=self.advance(30,price='1.02')
        row=self.manager.view_rows['BTC_ETH']
        self.assertEqual(row['state'],'HOLD');self.assertEqual(row['reason'],'HOLD_MARKET_BELOW_NET_ETH_TARGET')
        self.assertEqual(len(state['orders']),1)
        self.assertLess(state['auto']['performance']['midpoint_delta_eth'],0)
        self.assertIsNone(state['auto']['performance']['recoverable_eth'])

    def test_qualified_eth_exit_uses_current_native_price_and_cancels_when_target_no_longer_met(self):
        self.fill_seed();state=self.advance(30,price='.9')
        order=list(state['orders'].values())[-1]
        self.assertEqual((order['side'],order['limit_price']),('BUY',D('.9')))
        self.assertGreaterEqual(order['plan_receipt']['output_quantity'],state['auto']['intent_meta'][order['reference']]['required_eth'])
        self.advance(35,price='.9');self.advance(90,price='1.02');self.advance(95,price='1.03')
        state=self.advance(120,price='1.03')
        self.assertEqual(state['orders'][order['reference']]['state'],'CANCELED')
        self.assertEqual(len(state['orders']),2);self.assertEqual(state['wallet']['BTC'],D('.9954945'))

    def test_session_expiry_and_original_direction_deadline_cannot_renew(self):
        manager=self.create(duration_s=60);ref=self.opened(manager)
        self.advance(60,manager);state=self.advance(65,manager)
        self.assertEqual(state['mode'],'PAUSED');self.assertEqual(len(state['orders']),1)
        self.assertEqual(state['orders'][ref]['state'],'CANCELED')
        with self.assertRaises(PaperBlocked):manager.start(at=NOW+70)
        settings=direction_defaults();settings['ETH_BTC']['wait_s']=90
        manager=self.create(directions=settings);ref=self.opened(manager)
        self.advance(90,manager);self.advance(95,manager);state=self.advance(120,manager)
        self.assertEqual(len(state['orders']),1);self.assertEqual(state['auto']['last_reason'],'HOLD_ORIGINAL_CAMPAIGN_EXPIRED')

    def test_order_budget_exhaustion_pauses_without_new_money_or_silently_expanding_limits(self):
        manager=self.create(max_orders=2,order_ttl_s=60);self.opened(manager)
        for dt in (60,65,90,95,150,155,180):self.advance(dt,manager)
        state=manager.engine.private_state()
        self.assertEqual(state['mode'],'PAUSED');self.assertEqual(len(state['orders']),2)
        self.assertEqual(state['limits']['max_orders'],2);self.assertEqual(state['wallet'],{'ETH':D(1)})
        self.assertEqual(state['auto']['last_reason'],'PAPER_ORDER_BUDGET_EXHAUSTED_HOLD_INVENTORY')
        self.assertEqual(state['auto']['performance']['fees'],{})

    def test_stop_and_restart_pending_cancel_require_reconciliation_and_explicit_start(self):
        ref=self.opened();self.advance(60,price='1.01');self.manager.pause(at=NOW+60)
        restored=AutoPaper(self.manager.directory)
        self.assertEqual(restored.public()['state'],'RECONCILIATION_REQUIRED')
        self.assertEqual(len(restored.engine.private_state()['orders']),1)
        restored.reconcile(at=NOW+65);self.assertEqual(restored.public()['state'],'PAUSED')
        restored.on_frame(frame(NOW+70));self.assertEqual(len(restored.engine.private_state()['orders']),1)
        restored.start(at=NOW+75);state=self.advance(90,restored,price='1.03')
        self.assertEqual(len(state['orders']),2);self.assertEqual(state['auto']['kickoff_reference'],ref)
        self.assertEqual(state['auto']['intent_meta'][list(state['orders'])[-1]]['campaign_deadline'],NOW+3600)

    def test_both_policies_restore_and_frozen_short_parameters_cannot_change(self):
        old=AutoPaper(Path(self.temp.name)/'legacy');old.create(config(),at=NOW,funding=funding())
        self.assertEqual(AutoPaper(old.directory).config.frozen(),config().frozen())
        self.opened();restored=AutoPaper(self.manager.directory)
        self.assertEqual(restored.config.policy,SHORT_POLICY);self.assertIsNone(restored.last_problem)
        context=restored.engine.private_state()['auto'];context['config']['order_ttl_s']=300
        with self.assertRaisesRegex(PaperBlocked,'FROZEN_PAPER_POLICY'):restored.engine.checkpoint_context(context)
        context=restored.engine.private_state()['auto'];context['policy']=POLICY
        with self.assertRaisesRegex(PaperBlocked,'FROZEN_PAPER_POLICY'):restored.engine.checkpoint_context(context)
        context=restored.engine.private_state()['auto'];context['kickoff_reference']='another_seed'
        with self.assertRaisesRegex(PaperBlocked,'PAPER_KICKOFF_IDENTITY'):restored.engine.checkpoint_context(context)

    def test_stopped_order_past_child_expiry_cancels_after_explicit_resume_before_replacement(self):
        ref=self.opened();self.manager.pause(at=NOW+10)
        restored=AutoPaper(self.manager.directory);restored.reconcile(at=NOW+150)
        state=restored.engine.private_state()
        self.assertEqual(state['mode'],'PAUSED');self.assertEqual(state['orders'][ref]['state'],'OPEN')
        self.assertEqual(restored.engine.available('ETH'),0)
        restored.start(at=NOW+155);state=self.advance(160,restored)
        self.assertEqual(state['orders'][ref]['state'],'PENDING_CANCEL');self.assertEqual(len(state['orders']),1)
        self.advance(165,restored);state=self.advance(190,restored)
        self.assertEqual(state['orders'][ref]['state'],'CANCELED');self.assertEqual(len(state['orders']),2)
        self.assertEqual(state['auto']['kickoff_reference'],ref)
        self.assertEqual(state['wallet'],{'ETH':D(1)})
        self.assertEqual(state['auto']['intent_meta'][list(state['orders'])[-1]]['campaign_deadline'],NOW+3600)

    def test_short_policy_summary_is_an_allowlisted_enum_without_private_settings(self):
        self.opened();safe=self.manager.public();validate_public(safe)
        self.assertEqual(safe['policy'],SHORT_POLICY)
        for key in ('order_ttl_s','min_rest_s','reprice_bps','campaign_deadline','amount_eth'):
            self.assertNotIn(key,safe)


class OfflineVerifierProgress(unittest.TestCase):
    def test_slow_step_has_a_live_heartbeat_and_exceptions_join_its_worker(self):
        import io,threading
        from tools.RUN_OFFLINE_TESTS import Progress
        seen=threading.Event()
        class Output(io.StringIO):
            def write(self,value):
                result=super().write(value)
                if 'STILL RUNNING' in value:seen.set()
                return result
        stream=Output();progress=Progress(stream,interval=.01)
        with self.assertRaisesRegex(ValueError,'DECLARED_FIXTURE_EXCEPTION'):
            with progress:
                progress.update('declared slow fixture')
                self.assertTrue(seen.wait(2),'A running slow step must emit progress before it completes')
                raise ValueError('DECLARED_FIXTURE_EXCEPTION')
        self.assertIn('declared slow fixture',stream.getvalue())
        self.assertFalse(progress.thread.is_alive())

    def test_numbered_timing_output_retains_subtest_errors_and_failure_status(self):
        import io
        from tools.RUN_OFFLINE_TESTS import Progress,ProgressResult
        class DeclaredError(unittest.TestCase):
            def runTest(self):
                with self.subTest(case='declared error'):raise ValueError('DECLARED_SUBTEST_ERROR')
        stream=io.StringIO()
        with Progress(stream) as progress:
            suite=unittest.TestSuite((unittest.FunctionTestCase(lambda:None),DeclaredError()))
            result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=lambda *args,**kwargs:
                ProgressResult(*args,total=2,progress=progress,**kwargs)).run(suite)
        self.assertEqual(result.testsRun,2);self.assertEqual(len(result.errors),1)
        self.assertFalse(result.wasSuccessful());self.assertEqual(len(result.timings),2)
        for text in ('[1/2]','[2/2]','Test ','suite ','DECLARED_SUBTEST_ERROR','FAILED (errors=1)'):
            self.assertIn(text,stream.getvalue())
        self.assertFalse(progress.thread.is_alive())
