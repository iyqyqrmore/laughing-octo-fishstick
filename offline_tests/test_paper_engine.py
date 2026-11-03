"""Explicit fictitious executions, never quote touches or authenticated fills."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
import unittest

from coincat_adaptive_eth import Frame,recoverable_inventory
from coincat_paper_engine import PaperEngine,PaperLimits,PaperBlocked,ReplayDriver
from coincat_working_allocation import AllocationRow
from coincat_watchlist import WATCH_PAIRS
from offline_tests.test_adaptive_eth import inputs
from offline_tests.test_native_receipts import NOW


def observation(at=NOW,*,changes=None,rule_changes=None,tier_changes=None,excluded=()):
    x=inputs(at=at,fee='.01',evidence=False)
    x['_quotes']={p:(D(1),D('1.001'),at) for p in WATCH_PAIRS}
    x['_quotes'].update({'ETH-BTC':(D('1.009'),D('1.01'),at),
        'SOL-BTC':(D('.495'),D('.4954'),at),'SOL-ETH':(D('.4495'),D('.45'),at)})
    for rule in x['_rules'].values():rule.update(base_increment='.1',base_min_size='.1')
    x['_rules']['ETH-BTC'].update(base_min_size='.5',price_increment='.001')
    x['_rules']['SOL-BTC'].update(base_min_size='1',price_increment='.0001')
    x['_quotes'].update(changes or {})
    for pair,values in (rule_changes or {}).items():x['_rules'][pair].update(values)
    x['_tier'].update(tier_changes or {});x['_excluded']=excluded
    return Frame(**x)


def limits(**changes):
    base=PaperLimits(WATCH_PAIRS,{'ETH':D(1),'BTC':D(1),'SOL':D(10),'ADA':D(10),'LINK':D(10)},
        2,8,NOW+600,D('.02'))
    return replace(base,**changes)


class PaperLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'paper.sqlite3'
        self.engine=self.new()

    def new(self,name='paper.sqlite3',**changes):
        engine=PaperEngine.create(Path(self.temp.name)/name,initial_eth=D(1),limits=limits(**changes),
            at=NOW,simulation_ack='SIMULATION_ONLY')
        engine.start('start',at=NOW)
        return engine

    def seed(self,engine=None,**changes):
        args=dict(reference='seed',pair='ETH-BTC',side='SELL',source_budget=D(1),
            limit_price=D('1.01'),expires_at=NOW+120,frame=observation())
        args.update(changes)
        return (engine or self.engine).place('intent_'+args['reference'],**args)

    def event(self,kind,data,*,ref='seed',identity=None,at=NOW+1,engine=None):
        value=dict(event_id=identity or kind.lower()+'_'+ref,source='EXPLICIT_SIMULATION',
            kind=kind,reference=ref,at=at,data=data)
        return (engine or self.engine).ingest(value)

    def ack(self,ref='seed',**kwargs):
        return self.event('ACK',{'venue_order_id':'venue_'+ref},ref=ref,**kwargs)

    def fill(self,quantity,fee,*,ref='seed',fill_id='fill1',at=NOW+2,identity=None,engine=None,**changes):
        data=dict(fill_id=fill_id,price=D('1.01') if ref=='seed' else D('.495'),size=D(quantity),
            size_in_quote=False,commission=None if fee is None else D(fee),
            fee_currency='BTC',liquidity='MAKER',venue_order_id='venue_'+ref)
        data.update(changes)
        return self.event('FILL',data,ref=ref,identity=identity or 'event_'+fill_id,at=at,engine=engine)

    def fully_seed(self):
        self.seed();self.ack();self.fill('1','.0101')

    def rotation(self,engine=None,at=NOW+3):
        return (engine or self.engine).place('intent_sol',reference='sol',pair='SOL-BTC',side='BUY',
            source_budget=D('.9999'),limit_price=D('.495'),expires_at=NOW+120,frame=observation(at))

    def test_explicit_simulation_limits_and_exact_eth_only_initial_funding(self):
        state=self.engine.private_state()
        self.assertEqual(state['wallet'],{'ETH':D(1)})
        self.assertEqual(state['classification'],'SIMULATED_ASSUMPTION')
        self.assertEqual(self.engine.available('BTC'),0)
        for number,change in enumerate((dict(simulation_ack='LIVE'),dict(initial_eth=1.0),
                dict(initial_eth=D('NaN')),dict(limits=limits(products=('SOL-USD',))),
                dict(limits=limits(max_orders=0)),dict(limits=limits(source_caps={'USD':D(1)})),
                dict(limits=limits(max_fee_fraction=D('-.01'))),dict(limits=limits(expires_at=NOW)))):
            args=dict(initial_eth=D(1),limits=limits(),at=NOW,simulation_ack='SIMULATION_ONLY');args.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                PaperEngine.create(Path(self.temp.name)/f'bad{number}.sqlite3',**args)

    def test_proposal_uses_existing_manual_protected_excluded_funding_contract(self):
        args=dict(balances={'ETH':D(10),'BTC':D(50)},balances_at=NOW,
            draft=(AllocationRow('ETH',D(2),D(3),D(4)),))
        path=Path(self.temp.name)/'proposal.sqlite3'
        engine=PaperEngine.from_proposal(path,amount_eth=D(2),limits=limits(),at=NOW,
            simulation_ack='SIMULATION_ONLY',**args)
        self.assertEqual(engine.private_state()['wallet'],{'ETH':D(2)})
        for change in (dict(amount_eth=D(3)),dict(excluded=('ETH',)),dict(balances_at=NOW-121)):
            with self.subTest(change=change),self.assertRaisesRegex(PaperBlocked,'WORKING_ETH_UNAVAILABLE'):
                PaperEngine.from_proposal(Path(self.temp.name)/'denied.sqlite3',**{
                    **dict(amount_eth=D(2),limits=limits(),at=NOW,simulation_ack='SIMULATION_ONLY',**args),**change})

    def test_post_only_qualification_uses_actual_rules_quotes_fees_and_approved_products(self):
        args=(dict(limit_price=D('1.009')),dict(limit_price=D('1.0105')),
            dict(frame=observation(changes={'ETH-BTC':(D('1.009'),D('1.01'),NOW-31)})),
            dict(frame=observation(changes={'ETH-BTC':(D('1.009'),D('1.1'),NOW)})),
            dict(frame=observation(tier_changes={'fresh':False})),
            dict(frame=observation(tier_changes={'maker':D('.03')})),
            dict(frame=observation(rule_changes={'ETH-BTC':{'view_only':True}})),
            dict(frame=observation(rule_changes={'ETH-BTC':{'base_max_size':'.5'}})),
            dict(frame=observation(excluded=('BTC',))),dict(pair='ETH-USD'),
            dict(source_budget=D('1.01')),dict(expires_at=NOW))
        before=self.engine.private_state()
        for change in args:
            with self.subTest(change=change),self.assertRaises(ValueError):self.seed(**change)
            self.assertEqual(self.engine.private_state(),before)

    def test_a_quote_or_expiry_never_generates_an_execution(self):
        self.seed();self.ack()
        for i in range(3):self.engine.tick('tick'+str(i),at=NOW+10+i)
        self.assertEqual(self.engine.private_state()['wallet'],{'ETH':D(1)})
        self.assertEqual(self.engine.status()['simulated_fills'],0)
        self.engine.tick('expiry',at=NOW+120)
        order=self.engine.private_state()['orders']['seed']
        self.assertEqual(order['state'],'PENDING_CANCEL');self.assertEqual(order['reserved'],1)
        self.assertEqual(self.engine.available('ETH'),0)
        self.assertEqual(self.engine.pending_commands()[0]['kind'],'CANCEL_PAPER_ORDER')

    def test_reservation_prevents_competing_eth_intents_or_unfunded_btc_order(self):
        with self.assertRaisesRegex(PaperBlocked,'FUNDS_UNAVAILABLE'):self.rotation(at=NOW)
        self.seed(source_budget=D('.6'))
        with self.assertRaisesRegex(PaperBlocked,'FUNDS_UNAVAILABLE'):
            self.seed(reference='other',source_budget=D('.6'))
        self.assertEqual(self.engine.available('ETH'),D('.4'))
        self.assertEqual(self.engine.private_state()['wallet'],{'ETH':D(1)})

    def test_partial_below_full_order_minimum_is_booked_but_proceeds_stay_locked(self):
        self.seed();self.ack();self.fill('.4','.00404')
        state=self.engine.private_state();order=state['orders']['seed']
        self.assertEqual(order['state'],'PARTIAL');self.assertEqual(order['reserved'],D('.6'))
        self.assertEqual(state['wallet'],{'ETH':D('.6'),'BTC':D('.39996')})
        self.assertEqual(self.engine.available('ETH'),0);self.assertEqual(self.engine.available('BTC'),0)
        with self.assertRaisesRegex(PaperBlocked,'FUNDS_UNAVAILABLE'):
            self.engine.place('competing',reference='sol',pair='SOL-BTC',side='BUY',source_budget=D('.39996'),
                limit_price=D('.495'),expires_at=NOW+120,frame=observation(NOW+3,
                    rule_changes={'SOL-BTC':{'base_min_size':'.1'}}))

    def test_partial_cancel_releases_only_after_matching_explicit_terminal_totals(self):
        self.seed();self.ack();self.fill('.4','.00404')
        self.engine.request_cancel('cancel','seed')
        self.assertEqual(self.engine.available('ETH'),0);self.assertEqual(self.engine.available('BTC'),0)
        self.event('CANCEL_ACK',dict(cumulative_base=D('.4'),venue_order_id='venue_seed'),at=NOW+3)
        self.assertEqual(self.engine.available('ETH'),D('.6'))
        self.assertEqual(self.engine.available('BTC'),D('.39996'))
        self.assertEqual(self.engine.private_state()['orders']['seed']['state'],'CANCELED')
        self.assertEqual(self.engine.pending_commands(),[])

    def test_final_fill_wins_cancel_race_and_no_obsolete_cancel_is_dispatched(self):
        self.seed();self.ack();self.fill('.4','.00404')
        self.engine.request_cancel('cancel','seed')
        self.fill('.6','.00606',fill_id='fill2',at=NOW+3)
        self.assertEqual(self.engine.private_state()['orders']['seed']['state'],'FILLED')
        self.assertEqual(self.engine.available('BTC'),D('.9999'))
        self.assertEqual(self.engine.pending_commands(),[])
        self.event('CANCEL_ACK',dict(cumulative_base=D(1),venue_order_id='venue_seed'),at=NOW+4)
        self.assertEqual(self.engine.private_state()['orders']['seed']['state'],'FILLED')
        with self.assertRaisesRegex(PaperBlocked,'ALREADY_TERMINAL'):
            self.engine.mark_dispatched('late_send','cancel_seed',at=NOW+5)

    def test_quote_sized_buy_partials_charge_fees_exactly_once_and_preserve_native_units(self):
        self.fully_seed();self.rotation();self.ack('sol',at=NOW+3)
        self.assertEqual(self.engine.private_state()['orders']['sol']['base_size'],D(2))
        self.fill('.2475','.002475',ref='sol',size_in_quote=True,fill_id='sol1',at=NOW+4)
        self.assertEqual(self.engine.private_state()['wallet']['SOL'],D('.5'))
        self.assertEqual(self.engine.available('SOL'),0)
        self.fill('.7425','.007425',ref='sol',size_in_quote=True,fill_id='sol2',at=NOW+5)
        state=self.engine.private_state()
        self.assertEqual(state['wallet'],{'ETH':D(0),'BTC':D(0),'SOL':D(2)})
        self.assertEqual(state['orders']['sol']['spent_source'],D('.9999'))
        self.assertEqual(self.engine.available('SOL'),D(2))
        self.assertEqual(self.engine.status()['simulated_fills'],3)

    def test_different_delivery_ids_do_not_double_credit_the_same_fill(self):
        self.seed();self.ack();self.fill('.4','.00404')
        before=self.engine.private_state()
        self.assertEqual(self.fill('.4','.00404')['result'],'DUPLICATE_IGNORED')
        self.assertEqual(self.fill('.4','.00404',identity='delivery_again')['result'],'DUPLICATE_FILL_IGNORED')
        self.assertEqual(self.engine.private_state(),before)
        with self.assertRaisesRegex(PaperBlocked,'CONFLICTING_PAPER_FILL_ID'):
            self.fill('.5','.00505',identity='conflicting_delivery')
        self.assertEqual(self.engine.private_state()['wallet'],before['wallet'])
        self.assertEqual(self.engine.status()['mode'],'RECONCILIATION_REQUIRED')

    def test_conflicting_event_id_preserves_original_identity_and_halts_new_orders(self):
        self.seed();self.ack()
        with self.assertRaisesRegex(PaperBlocked,'CONFLICTING_PAPER_EVENT_ID'):
            self.event('ACK',{'venue_order_id':'different'},identity='ack_seed')
        self.assertEqual(self.ack()['result'],'DUPLICATE_IGNORED')
        self.assertEqual(self.engine.status()['mode'],'RECONCILIATION_REQUIRED')
        self.assertIsNone(self.engine.available('ETH'));self.assertEqual(self.engine.pending_commands(),[])

    def test_missing_fee_amount_or_currency_quarantines_without_guessing_proceeds(self):
        self.seed();self.ack();self.fill('1',None,fee_currency=None)
        self.assertEqual(self.engine.private_state()['wallet'],{'ETH':D(1)})
        self.assertIsNone(self.engine.available('ETH'));self.assertIsNone(self.engine.available('BTC'))
        self.assertEqual(self.engine.status()['unsettled_fills'],1)
        with self.assertRaisesRegex(PaperBlocked,'FEE_EVIDENCE_STILL_REQUIRED'):
            self.engine.reconcile('premature',wallet={'ETH':D(1)},orders={},at=NOW+3,source='SIMULATED_REPLAY')
        self.event('FEE_RESOLVED',dict(fill_id='fill1',commission=D('.0101'),fee_currency='BTC'),at=NOW+4)
        self.assertEqual(self.engine.private_state()['wallet'],{'ETH':D(0),'BTC':D('.9999')})
        self.assertEqual(self.engine.status()['mode'],'RECONCILIATION_REQUIRED')
        self.engine.reconcile('confirmed',wallet={'BTC':D('.9999')},orders={},at=NOW+5,source='SIMULATED_REPLAY')
        self.assertEqual(self.engine.status()['mode'],'PAUSED');self.assertEqual(self.engine.pending_commands(),[])
        self.engine.start('restart',at=NOW+6)
        self.assertEqual(self.engine.private_state()['limits']['expires_at'],NOW+600)
        self.assertEqual(self.fill('1',None,fee_currency=None)['result'],'DUPLICATE_IGNORED')
        self.assertEqual(self.engine.status()['simulated_fills'],1)

    def test_nonquote_fee_is_unsupported_until_explicit_quote_evidence_arrives(self):
        self.seed();self.ack();self.fill('.4','.00404',fee_currency='ETH')
        self.assertEqual(self.engine.private_state()['wallet'],{'ETH':D(1)})
        with self.assertRaisesRegex(PaperBlocked,'RESOLUTION_UNSUPPORTED'):
            self.event('FEE_RESOLVED',dict(fill_id='fill1',commission=D('.00404'),fee_currency='ETH'),at=NOW+3)
        self.event('FEE_RESOLVED',dict(fill_id='fill1',commission=D('.00404'),fee_currency='BTC'),
            identity='corrected_units',at=NOW+4)
        self.assertEqual(self.engine.private_state()['wallet']['BTC'],D('.39996'))
        self.assertEqual(self.engine.status()['mode'],'RECONCILIATION_REQUIRED')

    def test_overfill_wrong_price_units_float_rebate_fee_or_taker_never_mutates_wallet(self):
        cases=(dict(size=D('1.1')),dict(size=D('.45')),dict(price=D('1.009')),
            dict(price=D('1.0105')),dict(size=1.0),dict(commission=D('-.01')),
            dict(commission=D('.1')),dict(size_in_quote='false'),dict(liquidity='TAKER'))
        for i,change in enumerate(cases):
            with self.subTest(change=change):
                engine=self.new('case'+str(i)+'.sqlite3');self.seed(engine);self.ack(engine=engine)
                with self.assertRaises(ValueError):self.fill('1','.0101',engine=engine,**change)
                self.assertEqual(engine.private_state()['wallet'],{'ETH':D(1)})
                self.assertEqual(engine.status()['mode'],'RECONCILIATION_REQUIRED')
                self.assertIsNone(engine.available('BTC'))

    def test_fill_before_ack_and_later_duplicate_ack_preserve_partial_state(self):
        self.seed();self.fill('.4','.00404')
        self.assertEqual(self.ack()['result'],'DUPLICATE_ACK_IGNORED')
        self.assertEqual(self.engine.private_state()['orders']['seed']['state'],'PARTIAL')
        with self.assertRaisesRegex(PaperBlocked,'IDENTITY_CONFLICT'):
            self.event('ACK',{'venue_order_id':'wrong'},identity='bad_ack')

    def test_same_venue_order_id_cannot_identify_two_client_orders(self):
        self.seed(source_budget=D('.5'));self.ack()
        self.seed(reference='other',source_budget=D('.5'),frame=observation(NOW+1))
        with self.assertRaisesRegex(PaperBlocked,'VENUE_ID_REUSED'):
            self.event('ACK',{'venue_order_id':'venue_seed'},ref='other')
        self.assertEqual(self.engine.private_state()['wallet'],{'ETH':D(1)})

    def test_unseen_fill_after_confirmed_terminal_ack_is_a_reconciliation_conflict(self):
        self.seed();self.ack()
        self.event('CANCEL_ACK',dict(cumulative_base=D(0),venue_order_id='venue_seed'),at=NOW+3)
        before=self.engine.private_state()['wallet']
        with self.assertRaisesRegex(PaperBlocked,'LATE_FILL_CONFLICTS'):
            self.fill('.4','.00404',at=NOW+2)
        self.assertEqual(self.engine.private_state()['wallet'],before)
        self.assertIsNone(self.engine.available('ETH'))

    def test_terminal_cumulative_total_cannot_hide_missing_fills(self):
        self.seed();self.ack();self.fill('.4','.00404')
        with self.assertRaisesRegex(PaperBlocked,'HISTORY_INCOMPLETE'):
            self.event('CANCEL_ACK',dict(cumulative_base=D('.5'),venue_order_id='venue_seed'),at=NOW+3)
        self.assertEqual(self.engine.private_state()['orders']['seed']['reserved'],D('.6'))
        self.assertIsNone(self.engine.available('BTC'))

    def test_rejection_and_cancel_outcome_unknown_never_get_retried_automatically(self):
        self.seed();self.ack();self.engine.request_cancel('cancel','seed')
        self.event('OUTCOME_UNKNOWN',{'reason':'CANCEL_UNKNOWN'},at=NOW+3)
        self.assertEqual(self.engine.pending_commands(),[])
        self.assertIsNone(self.engine.available('ETH'))
        self.engine.reconcile('reconciled',wallet={'ETH':D(1)},orders={'seed':dict(state='CANCELED',
            filled_base=D(0),venue_order_id='venue_seed')},at=NOW+4,source='SIMULATED_REPLAY')
        self.assertEqual(self.engine.available('ETH'),1)
        other=self.new('rejected.sqlite3');self.seed(other)
        self.event('REJECT',dict(cumulative_base=D(0),venue_order_id=None),engine=other)
        self.assertEqual(other.available('ETH'),1)
        self.assertEqual(other.private_state()['orders']['seed']['state'],'REJECTED')

    def test_stop_and_session_expiry_retain_exposure_but_allow_pending_paper_cancellation(self):
        self.seed();self.engine.mark_dispatched('sent','place_seed',at=NOW)
        self.assertEqual(self.engine.pending_commands(),[]);self.ack()
        self.engine.stop('stop',at=NOW+2)
        self.assertEqual(self.engine.available('ETH'),0)
        self.engine.tick('expired',at=NOW+600)
        self.assertEqual(self.engine.status()['mode'],'PAUSED')
        self.assertEqual(self.engine.pending_commands()[0]['kind'],'CANCEL_PAPER_ORDER')
        self.engine.mark_dispatched('cancel_sent','cancel_seed',at=NOW+600)
        self.assertEqual(self.engine.pending_commands(),[])
        self.event('CANCEL_ACK',dict(cumulative_base=D(0),venue_order_id='venue_seed'),at=NOW+601)
        self.assertEqual(self.engine.available('ETH'),1)
        with self.assertRaisesRegex(PaperBlocked,'SESSION_EXPIRED'):self.engine.start('too_late',at=NOW+602)

    def test_unsent_or_unacknowledged_expired_intent_stays_locked_until_reconciled(self):
        self.seed()
        with self.assertRaisesRegex(PaperBlocked,'EXPIRED'):
            self.engine.mark_dispatched('late','place_seed',at=NOW+120)
        self.engine.tick('expire',at=NOW+120)
        self.assertEqual(self.engine.status()['mode'],'RECONCILIATION_REQUIRED')
        self.assertEqual(self.engine.pending_commands(),[])
        self.assertEqual(self.engine.private_state()['orders']['seed']['reserved'],1)

    def test_a_dispatched_command_never_grants_a_second_send_even_with_a_new_event_id(self):
        self.seed()
        first=self.engine.mark_dispatched('sent_once','place_seed',at=NOW)
        self.assertTrue(first['dispatch_permitted'])
        replay=self.engine.mark_dispatched('sent_once','place_seed',at=NOW)
        self.assertFalse(replay.get('dispatch_permitted',False))
        another=self.engine.mark_dispatched('new_delivery','place_seed',at=NOW+1)
        self.assertFalse(another['dispatch_permitted']);self.assertEqual(self.engine.pending_commands(),[])

    def test_explicit_not_accepted_snapshot_resolves_unknown_submission_without_a_venue_id(self):
        self.seed();self.event('OUTCOME_UNKNOWN',{'reason':'SUBMISSION_UNKNOWN'})
        self.engine.reconcile('not_accepted',wallet={'ETH':D(1)},orders={'seed':dict(state='REJECTED',
            filled_base=D(0),venue_order_id=None)},at=NOW+2,source='SIMULATED_REPLAY')
        self.assertEqual(self.engine.status()['mode'],'PAUSED')
        self.assertEqual(self.engine.available('ETH'),1)
        self.assertEqual(self.engine.pending_commands(),[])

    def test_restore_preserves_balances_and_deadlines_and_requires_reconciliation_and_start(self):
        self.seed();self.engine.mark_dispatched('sent','place_seed',at=NOW)
        before=self.engine.private_state()
        restored=PaperEngine.restore(self.path)
        self.assertEqual(restored.private_state()['wallet'],before['wallet'])
        self.assertEqual(restored.private_state()['orders'],before['orders'])
        self.assertEqual(restored.private_state()['limits'],before['limits'])
        self.assertEqual(restored.pending_commands(),[])
        with self.assertRaisesRegex(PaperBlocked,'RECONCILIATION_REQUIRED'):restored.start('bad_resume',at=NOW+3)
        with self.assertRaisesRegex(PaperBlocked,'NO_INVENTED_FUNDS'):
            restored.reconcile('extra_funds',wallet={'ETH':D(1),'BTC':D(10)},orders={},at=NOW+3,source='SIMULATED_REPLAY')
        restored.reconcile('evidence',wallet={'ETH':D(1)},orders={'seed':dict(state='OPEN',filled_base=D(0),
            venue_order_id='venue_seed')},at=NOW+4,source='SIMULATED_REPLAY')
        self.assertEqual(restored.status()['mode'],'PAUSED');self.assertEqual(restored.pending_commands(),[])
        restored.start('explicit_resume',at=NOW+5)
        self.assertEqual(restored.pending_commands(),[])
        with self.assertRaisesRegex(PaperBlocked,'STALE_PAPER_INSTANCE'):self.engine.tick('stale',at=NOW+6)
        self.assertEqual(self.engine.status()['mode'],'STALE_RELOAD_REQUIRED')
        self.assertIsNone(self.engine.available('ETH'))

    def test_missing_order_and_fill_history_snapshots_cannot_unlock_unknown_inventory(self):
        self.seed();self.ack();self.fill('.4','.00404')
        self.event('OUTCOME_UNKNOWN',{'reason':'TRANSPORT_GAP'},at=NOW+3)
        for i,orders in enumerate(({}, {'seed':dict(state='PARTIAL',filled_base=D('.5'),venue_order_id='venue_seed')})):
            with self.assertRaises(PaperBlocked):
                self.engine.reconcile('bad_snapshot'+str(i),wallet=self.engine.private_state()['wallet'],
                    orders=orders,at=NOW+4,source='SIMULATED_REPLAY')
            self.assertIsNone(self.engine.available('ETH'))

    def test_foreign_database_and_corrupted_paper_state_are_refused(self):
        foreign=Path(self.temp.name)/'financial.sqlite3'
        with closing(sqlite3.connect(foreign)) as db,db:db.execute('CREATE TABLE lots(id TEXT)')
        before=foreign.read_bytes()
        with self.assertRaisesRegex(PaperBlocked,'MUST_BE_EMPTY'):
            PaperEngine.create(foreign,initial_eth=D(1),limits=limits(),at=NOW,simulation_ack='SIMULATION_ONLY')
        with self.assertRaisesRegex(PaperBlocked,'WRONG_PAPER_DATABASE'):PaperEngine.restore(foreign)
        self.assertEqual(foreign.read_bytes(),before)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE paper_state SET payload='corrupt'")
        with self.assertRaisesRegex(PaperBlocked,'DIGEST'):PaperEngine.restore(self.path)

    def test_bounded_event_history_does_not_erase_existing_state(self):
        before=self.engine.private_state()
        with patch('coincat_paper_engine.MAX_EVENTS',1):
            with self.assertRaisesRegex(PaperBlocked,'EVENT_HISTORY_LIMIT'):self.engine.tick('over_limit',at=NOW+1)
        self.assertEqual(self.engine.private_state(),before)

    def test_session_open_and_total_order_limits_include_canceled_or_rejected_attempts(self):
        engine=self.new('bounded.sqlite3',max_open_orders=1,max_orders=2)
        self.seed(engine,source_budget=D('.5'))
        with self.assertRaisesRegex(PaperBlocked,'OPEN_ORDER_LIMIT'):
            self.seed(engine,reference='second',source_budget=D('.5'))
        self.event('CANCEL_ACK',dict(cumulative_base=D(0),venue_order_id='venue_seed'),engine=engine)
        self.seed(engine,reference='second',frame=observation(NOW+2))
        self.event('REJECT',dict(cumulative_base=D(0),venue_order_id=None),ref='second',engine=engine,at=NOW+3)
        with self.assertRaisesRegex(PaperBlocked,'SESSION_ORDER_LIMIT'):
            self.seed(engine,reference='third',frame=observation(NOW+4))
        self.assertEqual(engine.available('ETH'),1)

    def test_script_automates_only_settled_sequence_and_holds_underwater_sol_without_forced_sale(self):
        driver=ReplayDriver(self.engine,(
            dict(reference='seed',pair='ETH-BTC',side='SELL'),
            dict(reference='sol',pair='SOL-BTC',side='BUY')),order_lifetime_s=120)
        self.assertEqual(driver.advance(observation())['decision'],'PAPER_ORDER_REQUESTED')
        self.ack();self.fill('.4','.00404')
        self.assertEqual(driver.advance(observation(NOW+3))['decision'],'HOLD')
        self.fill('.6','.00606',fill_id='fill2',at=NOW+4)
        self.assertEqual(driver.advance(observation(NOW+5))['decision'],'PAPER_ORDER_REQUESTED')
        self.ack('sol',at=NOW+5);self.fill('2','.0099',ref='sol',fill_id='sol1',at=NOW+6)
        self.assertEqual(driver.advance(observation(NOW+7)),{'decision':'HOLD','reason':'APPROVED_PAPER_SCRIPT_COMPLETE'})
        self.engine.tick('later',at=NOW+600)
        state=self.engine.private_state()
        self.assertEqual(state['wallet'],{'ETH':D(0),'BTC':D(0),'SOL':D(2)})
        self.assertEqual(len(state['orders']),2);self.assertEqual(self.engine.pending_commands(),[])
        # The existing valuation routine still reports UNKNOWN without sized exit evidence.
        valuation=recoverable_inventory(state['wallet'],observation(NOW+600))
        self.assertIsNone(valuation['recoverable_eth'])
        status=self.engine.status()
        self.assertEqual(status['verified_exchange_fills'],0);self.assertEqual(status['real_orders'],0)
        self.assertIsNone(status['actual_profit_eth']);self.assertFalse(status['live_permission'])
        self.assertEqual(status['strategy_edge'],'NO_DEMONSTRATED_EDGE')

    def test_script_rejects_duplicate_references_and_keeps_hold_on_ineligible_frame(self):
        steps=(dict(reference='seed',pair='ETH-BTC',side='SELL'),)
        with self.assertRaisesRegex(PaperBlocked,'INVALID_PAPER_SCRIPT'):
            ReplayDriver(self.engine,steps+steps,order_lifetime_s=120)
        driver=ReplayDriver(self.engine,steps,order_lifetime_s=120)
        decision=driver.advance(observation(tier_changes={'fresh':False}))
        self.assertEqual(decision['decision'],'HOLD');self.assertEqual(self.engine.private_state()['orders'],{})

    def test_shipped_replay_runs_offline_without_private_data_and_has_exact_declared_outcomes(self):
        from tools.PAPER_LIFECYCLE_REPLAY import run_synthetic
        lines=[];result=run_synthetic(lines.append)
        self.assertEqual(result['wallet'],{'ETH':D(0),'BTC':D(0),'SOL':D(2)})
        self.assertEqual(result['status']['mode'],'PAUSED')
        self.assertEqual(result['status']['simulated_fills'],4)
        self.assertEqual(result['status']['real_orders'],0)
        self.assertEqual(result['orders']['seed']['state'],'FILLED')
        self.assertEqual(result['orders']['sol']['state'],'FILLED')
        self.assertEqual(result['duplicate']['result'],'DUPLICATE_FILL_IGNORED')
        self.assertIsNone(result['valuation']['recoverable_eth'])
        self.assertIn('SYNTHETIC','\n'.join(lines));self.assertIn('NO DEMONSTRATED EDGE','\n'.join(lines))
